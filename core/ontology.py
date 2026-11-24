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
    
