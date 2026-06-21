import asyncio
from typing import Any, Dict, List

from pymongo import AsyncMongoClient
from aiocache import Cache
from loguru import logger

from tashtiot_apis_library.fastapi_template.config_api import (
    LIVE_ALLOWED_NETWORKS, LIVE_ALLOWED_REGIONS, LIVE_ALLOWED_ISLANDS,
    LIVE_ALLOWED_ENVIRONMENTS, LIVE_ALLOWED_SPACES, LIVE_ALLOWED_PROJECTS,
    InfraMetadata,
)


class MongoConfigProvider:
    """All MongoDB access for the Config API plus in-memory caching (configurable
    TTL, default 60s) and the background allowlist-sync loop."""

    def __init__(
        self,
        mongo_client: AsyncMongoClient,
        db_name: str,
        *,
        enterprise_collection: str = "enterprise_configuration",
        naming_collection: str = "naming_conventions",
        projects_collection: str = "project_registry",
        cache_ttl_seconds: int = 60,
    ):
        db = mongo_client[db_name]
        # One purpose-built collection per shape, each holding a single document.
        self.enterprise = db[enterprise_collection]
        self.naming = db[naming_collection]
        self.projects = db[projects_collection]
        self._cache = Cache(Cache.MEMORY)
        self._cache_ttl = cache_ttl_seconds

    async def crawl_and_sync_keys(self, app_instance) -> None:
        """Discover allowed coordinate values from Mongo and hot-patch the live
        allowlists, then invalidate the cached Swagger schema so the enum
        dropdowns regenerate on the next request."""
        try:
            # 1. Naming convention coordinate tokens
            naming_doc = await self.naming.find_one({})
            if naming_doc:
                LIVE_ALLOWED_NETWORKS.clear()
                LIVE_ALLOWED_NETWORKS.update(naming_doc.get("network", {}).keys())
                LIVE_ALLOWED_REGIONS.clear()
                LIVE_ALLOWED_REGIONS.update(naming_doc.get("region", {}).keys())
                LIVE_ALLOWED_ISLANDS.clear()
                LIVE_ALLOWED_ISLANDS.update(naming_doc.get("island", {}).keys())
                LIVE_ALLOWED_ENVIRONMENTS.clear()
                LIVE_ALLOWED_ENVIRONMENTS.update(naming_doc.get("environment", {}).keys())
                LIVE_ALLOWED_SPACES.clear()
                LIVE_ALLOWED_SPACES.update(naming_doc.get("space", {}).keys())

            # 2. Global project registry catalog
            project_doc = await self.projects.find_one({})
            if project_doc:
                LIVE_ALLOWED_PROJECTS.clear()
                LIVE_ALLOWED_PROJECTS.update(project_doc.get("projects", []))

            # Invalidate the cached OpenAPI schema so it regenerates with fresh enums.
            app_instance.openapi_schema = None
        except Exception as e:
            logger.error(f"Synchronization pipeline loop operation failure: {e}")

    async def start_periodic_polling(self, app_instance, interval_seconds: int = 5) -> None:
        while True:
            await self.crawl_and_sync_keys(app_instance)
            await asyncio.sleep(interval_seconds)

    async def resolve_infra_config(self, meta: InfraMetadata) -> Dict[str, Any]:
        """Resolve config by merging `config` dicts along the coordinate path,
        root -> space -> network -> region -> island -> environment, where deeper
        layers override shallower ones. `project` is validated but is not part of
        the cascade path."""
        cache_key = f"cfg:{meta.space}:{meta.network}:{meta.region}:{meta.island}:{meta.environment}:{meta.project}"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        config_doc = await self.enterprise.find_one({})
        if not config_doc:
            return {}

        layers = []
        layers.append(config_doc.get("config", {}))

        space_node = config_doc.get("space", {}).get(meta.space, {})
        layers.append(space_node.get("config", {}))

        net_node = space_node.get("network", {}).get(meta.network, {})
        layers.append(net_node.get("config", {}))

        reg_node = net_node.get("region", {}).get(meta.region, {})
        layers.append(reg_node.get("config", {}))

        isl_node = reg_node.get("island", {}).get(meta.island, {})
        layers.append(isl_node.get("config", {}))

        env_node = isl_node.get("environment", {}).get(meta.environment, {})
        layers.append(env_node.get("config", {}))

        result = {}
        for layer in layers:
            result.update(layer)

        await self._cache.set(cache_key, result, ttl=self._cache_ttl)
        return result

    async def resolve_naming_convention(self, meta: InfraMetadata) -> Dict[str, Any]:
        """Resolve the naming token suffixes for the supplied coordinates. With no
        coordinates supplied, return the entire naming dictionary."""
        cache_key = f"name:{meta.space}:{meta.network}:{meta.region}:{meta.island}:{meta.environment}:{meta.project}"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        naming_doc = await self.naming.find_one({})
        if not naming_doc:
            return {}

        # No metadata coordinates supplied -> return the entire naming dictionary.
        if not any([meta.network, meta.region, meta.island, meta.environment, meta.space]):
            payload = {k: v for k, v in naming_doc.items() if k != "_id"}
            await self._cache.set(cache_key, payload, ttl=self._cache_ttl)
            return payload

        payload = {
            "network": naming_doc.get("network", {}).get(meta.network, {}),
            "region": naming_doc.get("region", {}).get(meta.region, {}),
            "island": naming_doc.get("island", {}).get(meta.island, {}),
            "environment": naming_doc.get("environment", {}).get(meta.environment, {}),
            "space": naming_doc.get("space", {}).get(meta.space, {}),
        }

        await self._cache.set(cache_key, payload, ttl=self._cache_ttl)
        return payload

    async def get_all_projects(self) -> List[str]:
        """Fetch the list of all registered platform project system names."""
        cache_key = "global:project_registry:all_names"

        cached_list = await self._cache.get(cache_key)
        if cached_list is not None:
            return cached_list

        project_doc = await self.projects.find_one({})
        if not project_doc:
            return []

        result_list = project_doc.get("projects", [])
        await self._cache.set(cache_key, result_list, ttl=self._cache_ttl)
        return result_list

    async def get_coordinate_catalog(self) -> Dict[str, List[str]]:
        """Return the valid values for every coordinate level plus the project list.

        Sourced from the `naming_conventions` per-level keys and the
        `project_registry` projects — the same data that drives the live
        allowlists — so clients can discover what they're allowed to query."""
        cache_key = "global:coordinate_catalog"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        naming_doc = await self.naming.find_one({}) or {}
        project_doc = await self.projects.find_one({}) or {}

        catalog = {
            "space": sorted(naming_doc.get("space", {}).keys()),
            "network": sorted(naming_doc.get("network", {}).keys()),
            "region": sorted(naming_doc.get("region", {}).keys()),
            "island": sorted(naming_doc.get("island", {}).keys()),
            "environment": sorted(naming_doc.get("environment", {}).keys()),
            "projects": sorted(project_doc.get("projects", [])),
        }

        await self._cache.set(cache_key, catalog, ttl=self._cache_ttl)
        return catalog
