"""Local document + response models for the MongoDB-backed Config API origin.

The shared coordinate/response contract (``InfraMetadata`` etc.) lives in the
library at ``tashtiot_apis_library.fastapi_template.config_api``. These models are
origin-specific:

- The three ``*Doc`` models describe the shape of each governing collection. They
  enforce the **envelope** (which top-level keys exist and their container types);
  the inner config/naming values stay ``Dict[str, Any]`` because they are
  intentionally free-form and heterogeneous (e.g. naming ``space`` values are bare
  strings while other levels are ``{host, cname}`` dicts). Enforcement happens at
  the **write boundary** (``scripts/seed_config.py``) and via per-collection
  ``$jsonSchema`` validators; provider reads stay dict-based / tolerant so a
  slightly-off document never 500s the read path.
- ``CoordinateCatalogResponse`` is the response model for the ``/coordinates``
  discovery route.
"""
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class EnterpriseConfigurationDoc(BaseModel):
    """The cascading configuration tree (collection ``enterprise_configuration``)."""

    config: Dict[str, Any] = Field(default_factory=dict)
    space: Dict[str, Any] = Field(default_factory=dict)


class NamingConventionsDoc(BaseModel):
    """Per-level host/cname token maps (collection ``naming_conventions``)."""

    network: Dict[str, Any] = Field(default_factory=dict)
    region: Dict[str, Any] = Field(default_factory=dict)
    island: Dict[str, Any] = Field(default_factory=dict)
    environment: Dict[str, Any] = Field(default_factory=dict)
    space: Dict[str, Any] = Field(default_factory=dict)


class ProjectRegistryDoc(BaseModel):
    """Flat catalog of authorized application names (collection ``project_registry``)."""

    projects: List[str] = Field(default_factory=list)


class CoordinateCatalogResponse(BaseModel):
    """All valid coordinate values per level, for the ``/coordinates`` route."""

    space: List[str] = Field(default_factory=list)
    network: List[str] = Field(default_factory=list)
    region: List[str] = Field(default_factory=list)
    island: List[str] = Field(default_factory=list)
    environment: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
