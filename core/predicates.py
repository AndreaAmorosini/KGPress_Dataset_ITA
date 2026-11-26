"""Load predicates registry and normalize arches"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypedDict, cast

from core.ontology import OntologyProfile
from core.schema_validation import ValidationIssue, validate_schema

TemporalPolicy = Literal["optional", "required", "forbidden"]

class _RoleQualifierPayload(TypedDict):
    required: bool
    value_source: Literal["participant_roles"]
    applies_to: Literal["subject"]
    
class _PredicatePayload(TypedDict):
    description: str
    family: str
    domain: list[str]
    range: list[str]
    temporal_policy: TemporalPolicy
    qualifiers: dict[str, _RoleQualifierPayload]
    cardinality: None
    incompatible_with: list[str]
    constraints: list[str]
    inverse: str | None
    mapping_refs: list[str]
    
class _AliasPayload(TypedDict):
    canonical_predicate: str
    swap_endpoints: bool
    
class _RegistryPayload(TypedDict):
    registry_version: str
    ontology_version: str
    predicate: dict[str, _PredicatePayload]
    input_aliases: dict[str, _AliasPayload]
    
@dataclass(frozen=True, slots=True)
class PredicateDefinition:
    description: str
    family: str
    domain: frozenset[str]
    range: frozenset[str]
    temporal_policy: TemporalPolicy
    participant_role_required: bool | None #None: not applicable, True: required, False: forbidden
    constraints: frozenset[str]
    inverse: str | None
    mapping_refs: tuple[str, ...]
    
@dataclass(frozen=True, slots=True)
class InputAlias:
    canonical_predicate: str
    swap_endpoints: bool
    
@dataclass(frozen=True, slots=True)
class PredicateRegistry:
    registry_version: str
    ontology_version: str
    predicates: Mapping[str, PredicateDefinition]
    input_aliases: Mapping[str, InputAlias]
    
class PredicateRegistryValidationError(ValueError):
    
    def __init__(self, path: Path, issues: list[ValidationIssue]) -> None:
        self.path = path
        self.issues = tuple(issues)
        details = "\n".join(f"{issue.path or '/'}: [{issue.code}] {issue.message}" for issue in self.issues)
        
        super().__init__(f"Validation failed for {self.path}: \n{details}")
        

def validate_predicate_registry(payload: object, ontology: OntologyProfile) -> list[ValidationIssue]:
    """Validate """
    issues = validate_schema("predicate_registry", payload)
    if issues:
        return issues
    
    profile = cast(_RegistryPayload, payload)
    predicates = profile["predicates"]
    aliases = profile["input_aliases"]
    
    def add(code: str, path: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                code=f"registry.{code}",
                path=path,
                severity="error",
                message=message
            )
        )
        
    if profile["ontology_version"] != ontology.ontology_version:
        add(
            "ontology_version_mismatch",
            "/ontology_version",
            f"Ontology version '{profile['ontology_version']}' does not match the provided ontology version '{ontology.ontology_version!r}'"
        )
        
    for predicate_id, definition in predicates.items():
        base = f"/predicates/{predicate_id}"
        
        for field, type_ids in (
            ("domain", definition["domain"]),
            ("range", definition["range"]),
        ):
            for index, type_id in enumerate(type_ids):
                if type_id not in ontology.entity_types:
                    add(
                        "unknown_entity_type",
                        f"{base}/{field}/{index}",
                        f"Unknown entity type '{type_id!r}'"
                    )
                    
        if "strict_event_order" in definition["constraints"] and (set(definition["domain"]) != {"Event"} or set(definition["range"]) != {"Event"}):
            add(
                "invalid_event_order_endpoints",
                f"{base}/constraints/{definition['constraints'].index('strict_event_order')}",
                "Constraint 'strict_event_order' can only be applied to predicates with domain and range of 'Event'"
            )
            
        inverse = definition["inverse"]
        if inverse is not None:
            alias = aliases.get(inverse)
            if (alias is None or alias["canonical_predicate"] != predicate_id or not alias["swap_endpoints"]):
                add(
                    "invalid_inverse",
                    f"{base}/inverse",
                    f"Inverse predicate '{inverse!r}' must be defined as an input alias with swap_endpoints=True and canonical_predicate='{predicate_id!r}'"
                )
                
    for alias_id, alias in aliases.items():
        base = f"/input_aliases/{alias_id}"
        if alias_id in predicates:
            add(
                "alias_collision",
                base,
                f"Input alias '{alias_id!r}' collides with a defined predicate"
            )
        if alias["canonical_predicate"] not in predicates:
            add(
                "unknown_canonical_predicate",
                f"{base}/canonical_predicate",
                f"Canonical predicate '{alias['canonical_predicate']!r}' is not defined in the registry"
            )
            
    return sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))


def load_predicate_registry(path: str | Path, ontology: OntologyProfile) -> PredicateRegistry:
    
    source = Path(path)
    payload: object  = json.loads(source.read_text(encoding="utf-8"))
    
    issues = validate_predicate_registry(payload, ontology)
    if issues:
        raise PredicateRegistryValidationError(source, issues)
    
    profile = cast(_RegistryPayload, payload)
    definitions: dict[str, PredicateDefinition] = {}
    
    for predicate_id, raw in profile["predicates"].items():
        role = raw["qualifiers"].get("participant_role")
        definitions[predicate_id] = PredicateDefinition(
            description=raw["description"],
            family=raw["family"],
            domain=frozenset(raw["domain"]),
            range=frozenset(raw["range"]),
            temporal_policy=raw["temporal_policy"],
            participant_role_required=role["required"] if role is not None else None,
            constraints=frozenset(raw["constraints"]),
            inverse=raw["inverse"],
            mapping_refs=tuple(raw["mapping_refs"])
        )
    
    return PredicateRegistry(
        registry_version=profile["registry_version"],
        ontology_version=profile["ontology_version"],
        predicates=MappingProxyType(definitions),
        input_aliases=MappingProxyType(
            {
                alias_id: InputAlias(
                    canonical_predicate=raw["canonical_predicate"],
                    swap_endpoints=raw["swap_endpoints"]
                )
                for alias_id, raw in profile["input_aliases"].items()
            }
        ),
    )
    
def normalize_triple(
    registry: PredicateRegistry,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> tuple[str, str, str]:
    """Normalize a declared alias; keep unknwon predicates as-is"""
    alias = registry.input_aliases.get(predicate)
    if alias is None:
        return subject_id, predicate, object_id
    
    if alias.swap_endpoints:
        return object_id, alias.canonical_predicate, subject_id
    
    return subject_id, predicate, object_id