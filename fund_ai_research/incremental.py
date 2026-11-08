"""Helpers for reusing research cards when only some funds changed."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any


def _as_dict(value: Any) -> dict:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _quality_facts(value: Any) -> dict:
    """Use the same shape for dataclass reports and serialized UI table rows."""
    row = _as_dict(value)
    row.pop("status", None)  # Derived display value, absent from QualityReport.
    warnings = row.get("warnings", [])
    if isinstance(warnings, str):
        warnings = [] if warnings in {"", "无"} else warnings.split("；")
    row["warnings"] = warnings
    return row


def research_fingerprint(metric: Any, quality: Any, events: Iterable[Any]) -> str:
    """Fingerprint the facts that feed one AI research card."""
    event_rows = [_as_dict(event) for event in events]
    event_rows.sort(key=_stable_json)
    payload = {
        "metric": _as_dict(metric),
        "quality": _quality_facts(quality),
        "events": event_rows,
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def fingerprints_for_records(metrics: Iterable[Any], quality: Iterable[Any], events: Iterable[Any]) -> dict[str, str]:
    quality_map = {_as_dict(item).get("code"): item for item in quality}
    event_map: dict[str, list[Any]] = {}
    for event in events:
        code = _as_dict(event).get("code")
        if code:
            event_map.setdefault(code, []).append(event)
    output = {}
    for metric in metrics:
        code = _as_dict(metric).get("code")
        if code:
            output[code] = research_fingerprint(metric, quality_map.get(code, {}), event_map.get(code, []))
    return output


def fingerprints_for_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, str]:
    """Build fingerprints from the JSON shape written by scheduled_research."""
    if not snapshot:
        return {}
    quality_map = {item.get("code"): item for item in snapshot.get("quality", []) if item.get("code")}
    event_map: dict[str, list[dict]] = {}
    for event in snapshot.get("events", []):
        code = event.get("code")
        if code:
            event_map.setdefault(code, []).append(event)
    output = {}
    for metric in snapshot.get("metrics", []):
        code = metric.get("code")
        if code:
            output[code] = research_fingerprint(metric, quality_map.get(code, {}), event_map.get(code, []))
    return output
