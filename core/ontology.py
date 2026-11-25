"""Loading and validation of local ontology profiles"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TypedDict, cast

from core.schema_validation import ValidationIssue, validate_schema

class _TypeDefinition(TypedDict):
    description: str
    
class _RoleDefinition(TypedDict):
    description: str
    allowed_entity_types: list[str]
    
class _OntologyPayload(TypedDict):
    ontology_version: str
    entity_types: dict[str, _TypeDefinition]
    event_types: dict[str, _TypeDefinition]
    participant_roles: dict[str, _RoleDefinition]
    diagnostic_tags: dict[str, str]
    
@dataclass(frozen=True, slots=True)
class ParticipantRole:
    description: str
    allowed_entity_types: frozenset[str]
    
@dataclass(frozen=True, slots=True)
class OntologyProfile:
    ontology_version: str
    entity_types: Mapping[str, str]
    event_types: Mapping[str, str]
    participant_roles: Mapping[str, ParticipantRole]
    diagnostic_tags: Mapping[str, str]
    
class OntologyValidationError(ValueError):
    
    def __init__(self, path: Path, issues: list[ValidationIssue]) -> None:
        self.path = path
        self.issues = tuple(issues)
        details = "\n".join(f"{issue.path or '/'}: [{issue.code}] {issue.message}" for issue in self.issues)
        super().__init__(f"Validation failed for {self.path}: \n{details}")
        
        
def validate_ontology(payload: object) -> list[ValidationIssue]:
    """Validate an ontology payload against the ontology schema."""
    issues = validate_schema("ontology", payload)
    if issues:
        return issues
    
    profile = cast(_OntologyPayload, payload)
    entity_types = profile["entity_types"]
    
    for role_id, role in sorted(profile["participant_roles"].items()):
        for index, type_id in enumerate(role["allowed_entity_types"]):
            if type_id not in entity_types:
                issues.append(
                    ValidationIssue(
                        code="ontology.unknown_entity_type",
                        path=f"/participant_roles/{role_id}/allowed_entity_types/{index}",
                        severity="error",
                        message=f"Unknown entity type '{type_id!r}'"
                    )
                )
                
    return issues

def load_ontology(path: str | Path) -> OntologyProfile:
    source = Path(path)
    payload: object = json.loads(source.read_text(encoding="utf-8"))
    
    issues = validate_ontology(payload)
    if issues:
        raise OntologyValidationError(source, issues)
    
    profile = cast(_OntologyPayload, payload)
    
    return OntologyProfile(
        ontology_version=profile["ontology_version"],
        entity_types=MappingProxyType(
            {
                type_id: type_def["description"]
                for type_id, type_def in profile["entity_types"].items()
            }
        ),
        event_types=MappingProxyType(
            {
                type_id: type_def["description"]
                for type_id, type_def in profile["event_types"].items()
            }
        ),
        participant_roles=MappingProxyType(
            {
                role_id: ParticipantRole(
                    description=role_def["description"],
                    allowed_entity_types=frozenset(role_def["allowed_entity_types"])
                )
                for role_id, role_def in profile["participant_roles"].items()
            }
        ),
        diagnostic_tags=MappingProxyType(dict(profile["diagnostic_tags"])),
    )