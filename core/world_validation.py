"""Structural, ontological and temporal validation of the synthetic world."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import NotRequired, TypedDict, cast

from core.ontology import OntologyProfile
from core.predicates import PredicateRegistry, PredicateDefinition
from core.schema_validation import ValidationIssue, validate_schema
from core.temporal import TemporalValue, strictly_precedes, validate_temporal_order

class _Entity(TypedDict):
    id: str
    type: str
    event_type: NotRequired[str]
    occurrence_time: NotRequired[TemporalValue]
    
class _Fact(TypedDict):
    id: str
    subject_id: str
    predicate: str
    object_id: str
    valid_time: NotRequired[TemporalValue]
    qualifiers: NotRequired[dict[str, object]]
    
class _World(TypedDict):
    ontology_version: str
    predicate_registry_version: str
    entities: list[_Entity]
    facts: list[_Fact]
    
def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=f"world.{code}",
        path=path,
        severity="error",
        message=message
    )
    
def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")

