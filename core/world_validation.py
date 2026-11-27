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

def _has_directed_cycle(edges: list[tuple[str, str]]) -> bool:
    """Detects the presenc of cycles in the graph, parallel arches are counted only once"""
    successors: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {}
    
    for subject, object_id in edges:
        indegree.setdefault(subject, 0)
        indegree.setdefault(object_id, 0)
        if object_id not in successors[subject]:
            successors[subject].add(object_id)
            indegree[object_id] += 1
            
    pending = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    
    while pending:
        node = pending.popleft()
        visited += 1
        for successor in successors.get(node, ()):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                pending.append(successor)
                
    return visited != len(indegree)

def _validate_qualifiers(
    qualifiers: dict[str, object],
    definition: PredicateDefinition,
    subject_type: str | None,
    ontology: OntologyProfile,
    path: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    policy = definition.participant_role_required
    role_path = f"{path}/participant_role"
    
    for name in qualifiers:
        if name != "participant_role" or policy is None:
            issues.append(
                _issue(
                    "unexpected_qualifier",
                    f"{path}/{_pointer_segment(name)}",
                    f"Unexpected qualifier '{name!r}'"
                )
            )
            
        if policy is None:
            return issues
        
        if "participant_role" not in qualifiers:
            if policy is True:
                issues.append(
                    _issue(
                        "missing_qualifier",
                        role_path,
                        f"Missing required qualifier 'participant_role' for predicate '{definition.name}'"
                    )
                )
            return issues
        
        value = qualifiers["participant_role"]
        role = ontology.participant_roles.get(value) if isinstance(value, str) else None
        
        if role is None:
            issues.append(
                _issue(
                    "unknown_participant_role",
                    role_path,
                    f"Unknown participant role '{value!r}'"
                )
            )
        elif subject_type is not None and subject_type not in role.allowed_entity_types:
            issues.append(
                _issue(
                    "invalid_role_subject_type",
                    role_path,
                    f"Participant role '{value!r}' is not allowed for subject type '{subject_type!r}'"
                )
            )
            
    return issues
    
def validate_world(
    payload: object,
    ontology: OntologyProfile,
    registry: PredicateRegistry
) -> list[ValidationIssue]:
    """Validate the world payload against the ontology and predicate registry."""
    issues = validate_schema("world", payload)
    if issues:
        return issues
    
    world = cast(_World, payload)
    
    for field, actual, expected in (
        ("ontology_version", world["ontology_version"], ontology.ontology_version),
        ("predicate_registry_version", world["predicate_registry_version"], registry.registry_version)
    ):
        if actual != expected:
            issues.append(
                _issue(
                    "version_mismatch",
                    f"/{field}",
                    f"Expected {field} '{expected!r}', but got '{actual!r}'"
                )
            )
            
    if registry.ontology_version != ontology.ontology_version:
        issues.append(
            _issue(
                "registry_ontology_mismatch",
                "/ontology_version",
                "The uploaded registry is not compatible with the uploaded ontology."
            )
        )
        
    if issues:
        return sorted(issues, key=lambda item: (item.path, item.code, item.message))
    
    entities: dict[str, _Entity] = {}
    ambiguous_ids: set[str] = set()
    
    for index, entity in enumerate(world["entities"]):
        path = f"/entities/{index}"
        entity_id = entity["id"]
        entity_type = entity["type"]

        if entity_id in entities:
            ambiguous_ids.add(entity_id)
            issues.append(
                _issue(
                    "duplicate_entity_id",
                    f"{path}/id",
                    f"Duplicate entity ID '{entity_id!r}'"
                )
            )
        else:
            entities[entity_id] = entity

        if entity_type not in ontology.entity_types:
            issues.append(
                _issue(
                    "unknown_entity_type",
                    f"{path}/type",
                    f"Unknown entity type '{entity_type!r}'"
                )
            )
            
        event_type = entity.get("event_type")
        if event_type is not None and event_type not in ontology.event_types:
            issues.append(
                _issue(
                    "unknown_event_type",
                    f"{path}/event_type",
                    f"Unknown event type '{event_type!r}'"
                )
            )
            
        occurrence_time = entity.get("occurrence_time")
        if occurrence_time is not None:
            issues.extend(
                validate_temporal_order(
                    occurrence_time,
                    path=f"{path}/occurrence_time"
                )
            )
            
    fact_ids: set[str] = set()
    acyclic_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    
    for index, fact in enumerate(world["facts"]):
        path = f"/facts/{index}"
        fact_id = fact["id"]
        if fact_id in fact_ids:
            issues.append(
                _issue(
                    "duplicate_fact_id",
                    f"{path}/id",
                    f"Duplicate fact ID '{fact_id!r}'"
                )
            )
        fact_ids.add(fact_id)
        
        resolved: dict[str, _Entity] = {}
        for field, entity_id in (("subject_id", fact["subject_id"]), ("object_id", fact["object_id"])):
            if entity_id not in entities:
                issues.append(
                    _issue(
                        "unknown_endpoint",
                        f"{path}/{field}",
                        f"Unknown entity ID '{entity_id!r}'"
                    )
                )
            elif entity_id not in ambiguous_ids:
                resolved[field] = entities[entity_id]
                
        valid_time = fact.get("valid_time")
        if valid_time is not None:
            issues.extend(
                validate_temporal_order(valid_time, path=f"{path}/valid_time")
            )
            
        predicate = fact["predicate"]
        definition = registry.predicates.get(predicate)
        if definition is None:
            alias = registry.input_aliases.get(predicate)
            if alias is None:
                issues.append(
                    _issue(
                        "unknown_predicate",
                        f"{path}/predicate",
                        f"Unknown predicate '{predicate!r}'"
                    )
                )
            else:
                issues.append(
                    _issue(
                        "noncanonical_predicate",
                        f"{path}/predicate",
                        f"Normalize {predicate!r} to its canonical form '{alias.canonical_predicate!r}'"
                    )
                )
                continue
            
        if definition.temporal_policy == "required" and valid_time is None:
            issues.append(
                _issue(
                    "missing_valid_time",
                    f"{path}/valid_time",
                    f"Missing required valid_time for predicate '{predicate!r}'"
                )
            )
        elif definition.temporal_policy == "forbidden" and valid_time is not None:
            issues.append(
                _issue(
                    "forbidden_valid_time",
                    f"{path}/valid_time",
                    f"Valid_time is forbidden for predicate '{predicate!r}'"
                )
            )
            
        endpoints_valid = len(resolved) == 2
        for field, allowed, code in (
            ("subject_id", definition.domain, "domain_violation"),
            ("object_id", definition.range, "range_violation")
        ):
            endpoint = resolved.get(field)
            if endpoint is None:
                continue
            
            endpoint_type = endpoint["type"]
            if endpoint_type not in ontology.entity_types:
                endpoints_valid = False
            elif endpoint_type not in allowed:
                endpoints_valid = False
                issues.append(
                    _issue(
                        code,
                        f"{path}/{field}",
                        f"Entity type '{endpoint_type!r}' is not allowed for predicate '{predicate!r}. Allowed: {', '.join(sorted(allowed))}'"
                    )
                )
                
        subject = resolved.get("subject_id")
        subject_type = subject["type"] if subject is not None else None
        issues.extend(
            _validate_qualifiers(
                fact.get("qualifiers", {}),
                definition,
                subject_type if subject_type in ontology.entity_types else None,
                ontology,
                f"{path}/qualifiers"
            )
        )
        
        if not endpoints_valid:
            continue
        
        subject_id , object_id = fact["subject_id"], fact["object_id"]
        if "no_self_loop" in definition.constraints and subject_id == object_id:
            issues.append(
                _issue(
                    "self_loop",
                    f"{path}/object_id",
                    f"Predicate '{predicate!r}' does not allow self-loops"
                )
            )
            continue
        
        if "acyclic" in definition.constraints:
            acyclic_edges[predicate].append((subject_id, object_id))
            
        if "strict_event_order" in definition.constraints:
            order = strictly_precedes(resolved["subject_id"].get("occurrence_time"), resolved["object_id"].get("occurrence_time"))
            if order is False:
                issues.append(
                    _issue(
                        "invalid_event_order",
                        f"{path}/predicate",
                        f"Predicate '{predicate!r}' requires that the subject precedes the object in time"
                    )
                )
                
    for predicate, edges in acyclic_edges.items():
        if _has_directed_cycle(edges):
            issues.append(
                _issue(
                    "predicate_cycle",
                    f"/facts",
                    f"Predicate '{predicate!r}' has a directed cycle in the facts"
                )
            )
            
    return sorted(issues, key=lambda item: (item.path, item.code, item.message))
        