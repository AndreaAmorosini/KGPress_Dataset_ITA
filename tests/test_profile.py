from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.mappings import load_ontology_mappings, validate_ontology_mappings
from core.ontology import OntologyProfile, OntologyValidationError, load_ontology
from core.predicates import (
    PredicateRegistry,
    load_predicate_registry,
    normalize_triple,
    validate_predicate_registry,
)
from core.schema_validation import validate_schema

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def read_profile(name: str) -> dict[str, Any]:
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def ontology() -> OntologyProfile:
    return load_ontology(CONFIG_DIR / "ontology.json")


@pytest.fixture
def registry(ontology: OntologyProfile) -> PredicateRegistry:
    return load_predicate_registry(CONFIG_DIR / "predicate_registry.json", ontology)


def test_committed_profiles_are_compatible(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    mappings = load_ontology_mappings(
        CONFIG_DIR / "ontology_mappings.json", ontology, registry
    )

    assert mappings["ontology_version"] == ontology.ontology_version
    assert mappings["predicate_registry_version"] == registry.registry_version
    assert ontology.participant_roles["speaker"].allowed_entity_types == {"Person"}
    assert registry.predicates["MANAGES"].domain == {"Organization"}
    assert registry.predicates["MANAGES"].range == {"Project"}

    entry = mappings["mappings"]["member_of_schema_org"]
    assert entry["local_id"] == "MEMBER_OF"
    assert "member_of_schema_org" in registry.predicates["MEMBER_OF"].mapping_refs
    assert entry["vocabulary"] in mappings["vocabularies"]


def test_ontology_loader_rejects_unknown_role_type(tmp_path: Path) -> None:
    profile = read_profile("ontology.json")
    profile["participant_roles"]["speaker"]["allowed_entity_types"] = ["UnknownType"]

    assert validate_schema("ontology", profile) == []
    path = tmp_path / "ontology.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(OntologyValidationError) as caught:
        load_ontology(path)

    assert caught.value.path == path
    assert [(issue.code, issue.path) for issue in caught.value.issues] == [
        (
            "ontology.unknown_entity_type",
            "/participant_roles/speaker/allowed_entity_types/0",
        )
    ]


def test_registry_rejects_unknown_endpoint_type(ontology: OntologyProfile) -> None:
    profile = read_profile("predicate_registry.json")
    profile["predicates"]["MANAGES"]["range"] = ["UnknownType"]

    assert validate_schema("predicate_registry", profile) == []
    issues = validate_predicate_registry(profile, ontology)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("registry.unknown_entity_type", "/predicates/MANAGES/range/0")
    ]


def test_registry_rejects_inverse_that_does_not_swap_endpoints(
    ontology: OntologyProfile,
) -> None:
    profile = read_profile("predicate_registry.json")
    profile["input_aliases"]["FOLLOWS"]["swap_endpoints"] = False

    issues = validate_predicate_registry(profile, ontology)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("registry.invalid_inverse", "/predicates/PRECEDES/inverse")
    ]


def test_registry_rejects_alias_collision(ontology: OntologyProfile) -> None:
    profile = read_profile("predicate_registry.json")
    profile["input_aliases"]["MANAGES"] = {
        "canonical_predicate": "REALIZES",
        "swap_endpoints": False,
    }

    issues = validate_predicate_registry(profile, ontology)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("registry.alias_collision", "/input_aliases/MANAGES")
    ]


@pytest.mark.parametrize(
    ("input_triple", "expected"),
    [
        (("A", "FOLLOWS", "B"), ("B", "PRECEDES", "A")),
        (("B", "PRECEDES", "A"), ("B", "PRECEDES", "A")),
        (("A", "si occupa di", "B"), ("A", "si occupa di", "B")),
    ],
    ids=["inverse", "canonical", "unknown"],
)
def test_normalize_triple(
    registry: PredicateRegistry,
    input_triple: tuple[str, str, str],
    expected: tuple[str, str, str],
) -> None:
    assert normalize_triple(registry, *input_triple) == expected


def test_mappings_reject_unknown_vocabulary(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    profile = read_profile("ontology_mappings.json")
    profile["mappings"]["member_of_schema_org"]["vocabulary"] = "unknown_vocab"

    assert validate_schema("ontology_mappings", profile) == []
    issues = validate_ontology_mappings(profile, ontology, registry)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("mappings.unknown_vocabulary", "/mappings/member_of_schema_org/vocabulary")
    ]


def test_mappings_reject_missing_registry_reference(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    profile = read_profile("ontology_mappings.json")
    del profile["mappings"]["member_of_schema_org"]

    issues = validate_ontology_mappings(profile, ontology, registry)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("mappings.missing_registry_mapping", "/mappings")
    ]


def test_mappings_reject_reference_assigned_to_another_predicate(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    profile = read_profile("ontology_mappings.json")
    profile["mappings"]["member_of_schema_org"]["local_id"] = "TAKES_PLACE_IN"

    issues = validate_ontology_mappings(profile, ontology, registry)

    assert {issue.code for issue in issues} == {
        "mappings.missing_registry_backlink",
        "mappings.wrong_registry_mapping_target",
    }


def test_mappings_reject_concept_both_mapped_and_unmapped(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    profile = read_profile("ontology_mappings.json")
    unmapped = profile["unmapped"]["predicate"]
    unmapped.append("MEMBER_OF")

    issues = validate_ontology_mappings(profile, ontology, registry)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("mappings.mapped_and_unmapped", f"/unmapped/predicate/{len(unmapped) - 1}")
    ]


def test_mappings_reject_registry_version_mismatch(
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> None:
    profile = read_profile("ontology_mappings.json")
    profile["predicate_registry_version"] = "999.0.0"

    issues = validate_ontology_mappings(profile, ontology, registry)

    assert [(issue.code, issue.path) for issue in issues] == [
        ("mappings.version_mismatch", "/predicate_registry_version")
    ]