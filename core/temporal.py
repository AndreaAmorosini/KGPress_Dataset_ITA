"""Temporal Checks for values allowed in the KGPress Ontology."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypedDict

from core.schema_validation import ValidationIssue

class CalendarDay(TypedDict):
    kind: Literal["date"]
    value: str
    
class Instant(TypedDict):
    kind: Literal["instant"]
    value: str
    
class DayInterval(TypedDict):
    kind: Literal["interval"]
    granularity: Literal["day"]
    start: str
    end: str
    
class TimestampInterval(TypedDict):
    kind: Literal["interval"]
    granularity: Literal["timestamp"]
    start: str
    end: str
    
TemporalValue = CalendarDay | Instant | DayInterval | TimestampInterval

@dataclass(frozen=True, slots=True)
class _DayBounds:
    start: date
    end: date
    
@dataclass(frozen=True, slots=True)
class _TimestampBounds:
    start: datetime
    end: datetime
    

def _bounds(value: TemporalValue) -> _DayBounds | _TimestampBounds:
    if value["kind"] == "date":
        day = date.fromisoformat(value["value"])
        return _DayBounds(start=day, end=day)
    
    if value["kind"] == "instant":
        instant = datetime.fromisoformat(value["value"])
        return _TimestampBounds(start=instant, end=instant)
    
    if value["granularity"] == "day":
        return _DayBounds(start=date.fromisoformat(value["start"]), end=date.fromisoformat(value["end"]))
    
    return _TimestampBounds(start=datetime.fromisoformat(value["start"]), end=datetime.fromisoformat(value["end"]))

def _is_ordered(bounds: _DayBounds | _TimestampBounds, *, is_interval: bool) -> bool:
    if isinstance(bounds, _TimestampBounds) and is_interval:
        return bounds.start < bounds.end
    
    return bounds.start <= bounds.end

def validate_temporal_order(value: TemporalValue, *, path: str = "") -> list[ValidationIssue]:
    """Check the order of start and end values after structural validation"""
    if value["kind"] != "interval":
        return []
    
    bounds = _bounds(value)
    if _is_ordered(bounds, is_interval=True):
        return []
    
    message = (
        "End date cannot be before start date" if isinstance(bounds, _DayBounds) else "End timestamp cannot be before start timestamp"
    )
    
    return [
        ValidationIssue(
            code="time.invalid_interval_order",
            path=f"{path}/end",
            severity="error",
            message=message
        )
    ]
    
def strictly_precedes(first: TemporalValue | None, second: TemporalValue | None) -> bool:
    """Check if the first temporal value strictly precedes the second one."""
    if first is None or second is None:
        return None
    
    left = _bounds(first)
    right = _bounds(second)
    
    if not _is_ordered(left, is_interval=first["kind"] == "interval"):
        return None
    
    if not _is_ordered(right, is_interval=second["kind"] == "interval"):
        return None
    
    if isinstance(left, _DayBounds) and isinstance(right, _DayBounds):
        return left.end < right.start
    
    if isinstance(left, _TimestampBounds) and isinstance(right, _TimestampBounds):
        return left.end < right.start
    
    return None
