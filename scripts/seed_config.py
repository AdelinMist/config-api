"""Seed the Config API's MongoDB with the three governing collections.

Destructive: drops and recreates each target collection. Every collection is
created with a ``$jsonSchema`` validator (envelope-level enforcement on write),
and every document is validated through its Pydantic model before insertion, so
malformed seed data fails fast — before any write. Run with the API's MongoDB
reachable:

    python scripts/seed_config.py

Mirrors the seed data the v1 Config API resolves (app/v1/config).
"""
import os
import sys
from pathlib import Path

from pymongo import MongoClient

# Allow running as a standalone script (python scripts/seed_config.py) by putting
# the repo root on the path so `app` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.v1.config.models import (  # noqa: E402
    EnterpriseConfigurationDoc,
    NamingConventionsDoc,
    ProjectRegistryDoc,
)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "infrastructure_governor")
ENTERPRISE_COLLECTION = os.environ.get("MONGO_COLLECTION_ENTERPRISE_CONFIG", "enterprise_configuration")
NAMING_COLLECTION = os.environ.get("MONGO_COLLECTION_NAMING", "naming_conventions")
PROJECTS_COLLECTION = os.environ.get("MONGO_COLLECTION_PROJECTS", "project_registry")


# Per-collection envelope validators. Inner config/naming values stay free-form
# (the cascade tree and naming tokens are intentionally heterogeneous); `_id` is
# allowed because `additionalProperties` is left at its default (true).
def _hierarchy_node(child_key=None, child_node=None):
    """A cascade node: a ``config`` object plus an optional child map keyed by name.

    ``additionalProperties: False`` rejects stray/typo'd keys (mirrors the Pydantic
    models' ``extra="forbid"``); the child map applies ``child_node`` to every name."""
    properties = {"config": {"bsonType": "object"}}
    if child_key:
        properties[child_key] = {"bsonType": "object", "additionalProperties": child_node}
    return {"bsonType": "object", "properties": properties, "additionalProperties": False}


# Built bottom-up: environment (leaf) → island → region → network → space.
_ENV_NODE = _hierarchy_node()
_ISLAND_NODE = _hierarchy_node("environment", _ENV_NODE)
_REGION_NODE = _hierarchy_node("island", _ISLAND_NODE)
_NETWORK_NODE = _hierarchy_node("region", _REGION_NODE)
_SPACE_NODE = _hierarchy_node("network", _NETWORK_NODE)

ENTERPRISE_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["config", "space"],
        # Top level intentionally allows extra props so Mongo's `_id` is permitted.
        "properties": {
            "config": {"bsonType": "object"},
            "space": {"bsonType": "object", "additionalProperties": _SPACE_NODE},
        },
    }
}

NAMING_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["network", "region", "island", "environment", "space"],
        "properties": {
            "network": {"bsonType": "object"},
            "region": {"bsonType": "object"},
            "island": {"bsonType": "object"},
            "environment": {"bsonType": "object"},
            "space": {"bsonType": "object"},
        },
    }
}

PROJECT_REGISTRY_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["projects"],
        "properties": {
            "projects": {"bsonType": "array", "items": {"bsonType": "string"}},
        },
    }
}


def seed_database():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]

    # Document A: Enterprise Cascading Hierarchical Configuration Tree
    config_tree = {
        "config": {
            "global_timeout_ms": 3000,
            "monitoring_provider": "datadog",
        },
        "space": {
            "core-infrastructure": {
                "config": {
                    "space_policy_class": "tier-1-governed"
                },
                "network": {
                    "backbone-net": {
                        "config": {
                            "ntp_server": "pool.ntp.org",
                            "dns_servers": ["10.0.0.1", "10.0.0.2"]
                        },
                        "region": {
                            "us-east": {
                                "config": {
                                    "aws_vpc_id": "vpc-0a1b2c3d"
                                },
                                "island": {
                                    "compute-island-a": {
                                        "config": {
                                            "cluster_size": 5
                                        },
                                        "environment": {
                                            "staging": {
                                                "config": {}
                                            },
                                            "production": {
                                                "config": {
                                                    "cluster_size": 20,
                                                    "debug_mode": False
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    # Document B: Network Topology Translation Naming Conventions
    naming_conventions = {
        "network": {
            "backbone-net": {"host": "bb", "cname": "net"}
        },
        "region": {
            "us-east": {"host": "use1", "cname": "east"}
        },
        "island": {
            "compute-island-a": {"host": "isla", "cname": "alpha"}
        },
        "environment": {
            "staging": {"host": "stg", "cname": "stage"},
            "production": {"host": "prd", "cname": "prod"}
        },
        "space": {
            "core-infrastructure": "core.internal",
            "tenant-alpha": "alpha.tenant.com"
        }
    }

    # Document C: Standalone Global Projects Inventory Registry
    project_registry = {
        "projects": [
            "payment-gateway",
            "authentication-service",
            "notification-engine",
            "data-warehouse-pipeline"
        ]
    }

    # Validate every document through its Pydantic model BEFORE touching Mongo —
    # malformed seed data raises here, before any destructive write.
    EnterpriseConfigurationDoc(**config_tree)
    NamingConventionsDoc(**naming_conventions)
    ProjectRegistryDoc(**project_registry)

    # Legacy single-collection layout (pre-split). Drop it so re-seeding leaves a
    # clean, three-collection database.
    db.drop_collection("global_configs")

    plan = [
        (ENTERPRISE_COLLECTION, ENTERPRISE_SCHEMA, config_tree),
        (NAMING_COLLECTION, NAMING_SCHEMA, naming_conventions),
        (PROJECTS_COLLECTION, PROJECT_REGISTRY_SCHEMA, project_registry),
    ]

    for name, validator, document in plan:
        # Destructive: drop and recreate so the collection always carries the
        # current validator. Idempotent across re-runs.
        db.drop_collection(name)
        db.create_collection(
            name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )
        db[name].insert_one(document)

    print("Successfully seeded the three governing collections into MongoDB.")
    client.close()


if __name__ == "__main__":
    seed_database()
