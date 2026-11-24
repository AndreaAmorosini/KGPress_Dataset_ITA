"""Structural Validation of JSON Schema documents."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Literal
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

_SCHEMA_SUFFIX = ".schema.json"
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
_URI_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*:"
    r"(?:[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=-]|%[0-9A-Fa-f]{2})+"
)

@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Validation problem, path is JSON pointer o empty string for the root document."""
    
    code: str
    path: str
    severity: Literal["error", "warning"]
    message: str
    
def _is_calendar_date(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if _DATE_RE.fullmatch(value) is None:
        return False
    
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True

def _is_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if _TIMESTAMP_RE.fullmatch(value) is None:
        return False
    
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    
    return True

def _is_absolute_uri(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if _URI_RE.fullmatch(value) is None or value.count("#") > 1:
        return False
    
    try:
        parts = urlsplit(value)
        if parts.scheme in {"http", "https"}:
            if not parts.hostname:
                return False
            
            port = parts.port 
            if port is not None and not 0 <= port <= 65535:
                return False
            
    except ValueError:
        return False
    
    return bool(parts.scheme)

def _make_format_checker() -> FormatChecker:
    checker = FormatChecker(formats=())
    checker.checks("date", raises=ValueError)(_is_calendar_date)
    checker.checks("date-time", raises=ValueError)(_is_timestamp)
    checker.checks("uri", raises=ValueError)(_is_absolute_uri)
    return checker


def _json_pointer(parts: Iterable[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)

@lru_cache(maxsize=1)
def _load_validators() -> dict[str, Draft202012Validator]:
    schema_dir = files("core").joinpath("schemas")
    schemas = {}
    resources = {}
    
    for path in sorted(schema_dir.iterdir(), key=lambda entry: entry.name):
        if not path.is_file() or not path.name.endswith(_SCHEMA_SUFFIX):
            continue
        
        kind = path.name.removesuffix(_SCHEMA_SUFFIX)
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Schema senza ID: {path.name}")
        if schema_id in resources:
            raise ValueError(f"ID duplicato in {path.name}: {schema_id}")
        
        schemas[kind] = schema
        resources[schema_id] = Resource.from_contents(schema)
        
    if "common" not in schemas:
        raise RuntimeError("Schema 'common' mancante")
    
    registry = Registry().with_resources(resources.items())
    format_checker = _make_format_checker()
    
    return {
        kind: Draft202012Validator(schema, registry=registry, format_checker=format_checker)
        for kind, schema in schemas.items()
        if kind != "common"
    }
    
def available_schema_kinds() -> tuple[str, ...]:
    return tuple()
        
                
        