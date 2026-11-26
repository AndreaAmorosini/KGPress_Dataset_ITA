from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from core.ontology import OntologyProfile
from core.predicates import PredicateRegistry
from core.schema_validation import ValidationIssue, validate_schema


class Vocabulary(TypedDict):
    version: str
    source_url: str
    
class MappingEntry(TypedDict):
    local_kind: Literal[
        "entity_type", "event_type", "document_type", "document_link", "predicate"
    ]
    local_id: str
    vocabulary: str
    match: Literal["exact", "close", "broad", "narrow"]
    target_iri: str
    rationale: str
    
class TopicReference(TypedDict):
    vocabulary: Literal["iptc_media_topics"]
    target_iri: str
    label_en: str
    note: NotRequired[str]
    
class OntologyMappings(TypedDict):
    mapping_version: str
    ontology_version: str
    predicate_registry_version: str
    vocabularies: dict[str, Vocabulary]
    mappings: dict[str, MappingEntry]
    unmapped: dict[str, list[str]]
    reference_terms: dict[str, list[str]]
    topic_reference: dict[str, TopicReference]
    
class OntologyMappingsValidationError(ValueError):
    
    def __init__(self, path: Path, issues: list[ValidationIssue]) -> None:
        self.path = path
        self.issues = tuple(issues)
        details = "\n".join(f" {issue.path or '/'} [{issue.code}]  {issue.message}" for issue in self.issues)
        super().__init__(f"Validation failed for {self.path}: \n{details}")

def validate_ontology_mappings(payload: object, ontology: OntologyProfile, registry: PredicateRegistry) -> list[ValidationIssue]:
    issues = validate_schema("ontology_mappings", payload)
    if issues:
        return issues
    
    profile = cast(OntologyMappings, payload)
    mappings = profile["mappings"]
    vocabularies = profile["vocabularies"]
    local_ids: dict[str, Collection[str]] = {
        "entity_type": ontology.entity_types,
        "event_type": ontology.event_types,
        "predicate": registry.predicates,
        "document_type": {"Article", "ArticleClaim"},
        "document_link": {"ArticleClaim.article_id"}
    }
    
    def add(code: str, path: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                code=f"mappings.{code}",
                path=path,
                severity="error",
                message=message
            )
        )
        
    for field, declared, expected in (
        ("ontology_version", profile["ontology_version"], ontology.ontology_version),
        ("predicate_registry_version", profile["predicate_registry_version"], registry.registry_version)
    ):
        if declared != expected:
            add(
                "version_mismatch",
                f"/{field}",
                f"Declared {field} '{declared!r}' does not match the expected version '{expected!r}'"
            )
            
    if registry.ontology_version != ontology.ontology_version:
        add(
            "registry_ontology_mismatch",
            "/ontology_version",
            f"Predicate registry ontology version '{registry.ontology_version!r}' does not match the provided ontology version '{ontology.ontology_version!r}'"
        )
        
    mapped_concepts: set[tuple[str, str]] = set()
    
    for mapping_id, entry in mappings.items():
        base = f"/mappings/{mapping_id}"
        kind, local_id = entry["local_kind"], entry["local_id"]
        mapped_concepts.add((kind, local_id))
        
        if local_id not in local_ids[kind]:
            add(
                "unknown_local_id",
                f"{base}/local_id",
                f"Unknown local {kind} '{local_id!r}'"
            )
            
        if entry["vocabulary"] not in vocabularies:
            add(
                "unknown_vocabulary",
                f"{base}/vocabulary",
                f"Unknown vocabulary '{entry['vocabulary']!r}'"
            )
            
        if kind == "predicate" and local_id in registry.predicates:
            if mapping_id not in registry.predicates[local_id].mapping_refs:
                add(
                    "missing_registry_backlink",
                    base,
                    f"Mapping '{mapping_id}' is not listed in the predicate registry for predicate '{local_id!r}'"
                )
    
    for kind, ids in profile["unmapped"].items():
        for index, local_id in enumerate(ids):
            path = f"/unmapped/{kind}/{index}"
            if local_id not in local_ids[kind]:
                add(
                    "unknown_local_id",
                    path,
                    f"ID '{local_id!r}' is not a known local {kind}"
                )
            if (kind, local_id) in mapped_concepts:
                add(
                    "mapped_and_unmapped",
                    path,
                    f"ID '{local_id!r}' is listed as unmapped but also has a mapping"
                )
                
    for vocabulary in profile["reference_terms"]:
        if vocabulary not in vocabularies:
            add(
                "unknown_vocabulary",
                f"/reference_terms/{vocabulary}",
                f"Unknown vocabulary '{vocabulary!r}'"
            )
            
    for cluster_id, topic in profile["topic_references"].items():
        if topic["vocabulary"] not in vocabularies:
            add(
                "unknown_vocabulary",
                f"/topic_references/{cluster_id}/vocabulary",
                f"Unknown vocabulary '{topic['vocabulary']!r}'"
            )
            
    for predicate_id, definition in registry.predicates.items():
        for mapping_id in definition.mapping_refs:
            entry = mappings.get(mapping_id)
            if entry is None:
                add(
                    "missing_registry_mapping",
                    "/mappings",
                    f"Predicate '{predicate_id!r}' references mapping '{mapping_id!r}' which is not defined in the mappings"
                )
            elif (entry["local_kind"], entry["local_id"]) != ("predicate", predicate_id):
                add(
                    "wrong_registry_mapping_target",
                    f"/mappings/{mapping_id}",
                    f"Predicate '{predicate_id!r}' references mapping '{mapping_id!r}' which does not target the predicate (local_kind={entry['local_kind']!r}, local_id={entry['local_id']!r})"
                )
    return sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
    
def load_ontology_mappings(
    path: str | Path,
    ontology: OntologyProfile,
    registry: PredicateRegistry,
) -> OntologyMappings:
    source = Path(path)
    payload: object = json.loads(source.read_text(encoding="utf-8"))
    
    issues = validate_ontology_mappings(payload, ontology, registry)
    if issues:
        raise OntologyMappingsValidationError(source, issues)
    
    return cast(OntologyMappings, payload)
