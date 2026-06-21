"""Envelope validation for the per-collection document models.

These guard the write boundary (scripts/seed_config.py validates through them
before any insert). They enforce the envelope — which top-level keys exist and
their container types — while leaving inner config/naming values free-form.
"""
import pytest
from pydantic import ValidationError

from app.v1.config.models import (
    EnterpriseConfigurationDoc,
    NamingConventionsDoc,
    ProjectRegistryDoc,
    SpaceNode,
)
from tests.conftest import ENTERPRISE_CONFIG_DOC, NAMING_DOC, PROJECT_REGISTRY_DOC


def _strip_doc_type(doc):
    return {k: v for k, v in doc.items() if k != "doc_type"}


class TestSeedDocsValidate:
    def test_enterprise_seed_is_valid(self):
        EnterpriseConfigurationDoc(**_strip_doc_type(ENTERPRISE_CONFIG_DOC))

    def test_naming_seed_is_valid(self):
        # Heterogeneous space (strings) + dict levels both accepted.
        NamingConventionsDoc(**_strip_doc_type(NAMING_DOC))

    def test_project_registry_seed_is_valid(self):
        ProjectRegistryDoc(**_strip_doc_type(PROJECT_REGISTRY_DOC))


class TestRejectsObviousViolations:
    def test_projects_must_be_a_list_of_strings(self):
        with pytest.raises(ValidationError):
            ProjectRegistryDoc(projects="payment-gateway")

    def test_projects_items_must_be_strings(self):
        with pytest.raises(ValidationError):
            ProjectRegistryDoc(projects=[123, 456])

    def test_naming_level_must_be_a_mapping(self):
        with pytest.raises(ValidationError):
            NamingConventionsDoc(network="not-an-object")

    def test_enterprise_config_must_be_a_mapping(self):
        with pytest.raises(ValidationError):
            EnterpriseConfigurationDoc(config="not-an-object")


class TestDefaults:
    def test_all_fields_default_empty(self):
        # Missing levels default to empty containers (lenient envelope).
        assert NamingConventionsDoc().space == {}
        assert ProjectRegistryDoc().projects == []
        assert EnterpriseConfigurationDoc().config == {}


class TestEnterpriseHierarchy:
    """The enterprise model is fully typed down every cascade level."""

    def test_full_depth_tree_validates_and_parses(self):
        doc = {
            "config": {"global_timeout_ms": 3000},
            "space": {
                "core": {
                    "config": {"policy": "tier-1"},
                    "network": {
                        "bb": {
                            "config": {},
                            "region": {
                                "us-east": {
                                    "config": {},
                                    "island": {
                                        "isla": {
                                            "config": {},
                                            "environment": {
                                                "production": {"config": {"cluster_size": 20}},
                                            },
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
            },
        }
        parsed = EnterpriseConfigurationDoc(**doc)
        # Nodes are parsed into typed models, not left as raw dicts.
        env = parsed.space["core"].network["bb"].region["us-east"].island["isla"].environment["production"]
        assert env.config == {"cluster_size": 20}

    def test_rejects_wrong_type_deep_in_tree(self):
        with pytest.raises(ValidationError):
            EnterpriseConfigurationDoc(space={"core": {"network": "not-an-object"}})

    def test_rejects_unknown_key_at_a_node(self):
        # extra="forbid": a typo'd level/key is rejected rather than silently kept.
        with pytest.raises(ValidationError):
            EnterpriseConfigurationDoc(space={"core": {"netwrok": {}}})

    def test_node_config_must_be_a_mapping(self):
        with pytest.raises(ValidationError):
            SpaceNode(config="not-an-object")
