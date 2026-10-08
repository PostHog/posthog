"""The variant analysis scout: a customer-run scout that compares an experiment scanner's variants.

The scout runs on the Signals scout schedule and submits one structured record per run, and the
variants readout shows the newest one. The record's schema lives here, next to the reader, so the
two can't drift: the scanner scout endpoint attaches it when a scout is created for this purpose.

The scout writes its own counts, so they are its claims, not Replay Vision's. The readout keeps its
live per-variant counts as the trusted numbers, shows a record only for the scanner's current
version, and keeps only cited observations that belong to the variant they are cited for.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade

logger = structlog.get_logger(__name__)

# pinned: marks the scouts the readout reads and the sweep pauses. Stored on the scout's config tags.
VARIANT_ANALYSIS_TAG = "replay-vision-variant-analysis"

MAX_VARIANTS = 8
MAX_LINES_PER_VARIANT = 5
MAX_DIFFERENCES = 5
MAX_EXAMPLES_PER_LINE = 2
_THEME_CHARS = 80
_STATEMENT_CHARS = 240


_COUNTS_BY_VARIANT: dict[str, Any] = {
    "type": "object",
    "maxProperties": MAX_VARIANTS,
    "additionalProperties": {"type": "integer", "minimum": 0},
}

# One record per run: the whole analysis. Draft 2020-12, local refs only and no regex keywords, as the
# Signals structured output channel requires.
VARIANT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["scanner_version", "observations_read", "variants", "differences"],
    "properties": {
        "scanner_version": {
            "type": "integer",
            "minimum": 1,
            "description": "The scanner's `scanner_version` when you read it. Read only that version's observations.",
        },
        "observations_read": {
            **_COUNTS_BY_VARIANT,
            "description": "How many summaries you read per variant key: the denominator of every count below.",
        },
        "variants": {
            "type": "object",
            "maxProperties": MAX_VARIANTS,
            "description": "Per variant key, its most notable themes, most common first.",
            "additionalProperties": {
                "type": "array",
                "maxItems": MAX_LINES_PER_VARIANT,
                "items": {"$ref": "#/$defs/digest_line"},
            },
        },
        "differences": {
            "type": "array",
            "maxItems": MAX_DIFFERENCES,
            "description": "What differs between variants, most meaningful first. Empty when nothing does.",
            "items": {"$ref": "#/$defs/difference"},
        },
    },
    "$defs": {
        "digest_line": {
            "type": "object",
            "additionalProperties": False,
            "required": ["theme", "statement", "count"],
            "properties": {
                "theme": {"type": "string", "minLength": 1, "maxLength": _THEME_CHARS},
                "statement": {"type": "string", "minLength": 1, "maxLength": _STATEMENT_CHARS},
                "count": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Summaries of this variant you read that show the theme.",
                },
                "example_observation_ids": {
                    "type": "array",
                    "maxItems": MAX_EXAMPLES_PER_LINE,
                    "items": {"type": "string", "maxLength": 64},
                },
            },
        },
        "difference": {
            "type": "object",
            "additionalProperties": False,
            "required": ["theme", "statement", "counts"],
            "properties": {
                "theme": {"type": "string", "minLength": 1, "maxLength": _THEME_CHARS},
                "statement": {"type": "string", "minLength": 1, "maxLength": _STATEMENT_CHARS},
                "counts": {**_COUNTS_BY_VARIANT, "description": "Summaries showing the theme, per variant key."},
            },
        },
    },
}


def variant_analysis_config(config_options: dict[str, Any]) -> dict[str, Any]:
    """The scout config options with the variant analysis schema and tag attached."""
    tags = [*(config_options.get("tags") or []), VARIANT_ANALYSIS_TAG]
    return {**config_options, "structured_output_schema": VARIANT_ANALYSIS_SCHEMA, "tags": sorted(set(tags))}


@frozen
class VariantAnalysisLine:
    theme: str
    statement: str
    count: int
    example_observation_ids: tuple[str, ...]


@frozen
class VariantAnalysisDifference:
    theme: str
    statement: str
    counts: dict[str, int]


@frozen
class VariantAnalysis:
    scout_config_id: str
    scout_enabled: bool
    recorded_at: datetime | None
    scanner_version: int | None
    # Whether the newest record covers the scanner's current version. Only a current record is shown.
    current: bool
    observations_read: dict[str, int]
    lines: dict[str, tuple[VariantAnalysisLine, ...]]
    differences: tuple[VariantAnalysisDifference, ...]


def variant_analysis_for_scanner(
    scanner: ReplayScanner, *, resolve_citations: Callable[[set[str]], dict[str, str]]
) -> VariantAnalysis | None:
    """The scanner's variant analysis, or None when no variant analysis scout exists.

    `resolve_citations` takes the observation ids the record cites and returns, for each one the
    caller may show, its variant. A cited id it leaves out (another scanner's, one the caller can't
    read) or maps to another variant is dropped.
    """
    scouts = signals_facade.scouts_for_source(
        scanner.team_id, SCOUT_SOURCE_PRODUCT, str(scanner.id), tag=VARIANT_ANALYSIS_TAG
    )
    if not scouts:
        return None
    scout = next((candidate for candidate in reversed(scouts) if candidate.enabled), scouts[-1])
    record = signals_facade.latest_structured_output_for_source(
        scanner.team_id, SCOUT_SOURCE_PRODUCT, str(scanner.id), tag=VARIANT_ANALYSIS_TAG
    )
    payload = record.payload if record is not None else {}
    version = payload.get("scanner_version")
    current = record is not None and version == scanner.scanner_version
    cited_variants = resolve_citations(_cited_ids(payload.get("variants"))) if current else {}
    return VariantAnalysis(
        scout_config_id=scout.config_id,
        scout_enabled=scout.enabled,
        recorded_at=record.recorded_at if record is not None else None,
        scanner_version=version if isinstance(version, int) else None,
        current=current,
        observations_read=_counts(payload.get("observations_read")) if current else {},
        lines=_lines(payload.get("variants"), cited_variants) if current else {},
        differences=_differences(payload.get("differences")) if current else (),
    )


def pause_variant_analysis_scouts(scanner: ReplayScanner) -> int:
    """Turn off the scanner's enabled variant analysis scouts and return how many were turned off.

    Called once the scanner has stopped for good, so the scout stops re-reading unchanged data on the
    customer's bill. It is not turned back on by a relaunch: the person does that.
    """
    paused = 0
    for scout in signals_facade.scouts_for_source(
        scanner.team_id, SCOUT_SOURCE_PRODUCT, str(scanner.id), tag=VARIANT_ANALYSIS_TAG
    ):
        if scout.enabled and signals_facade.update_scout_for_source(
            scanner.team_id, SCOUT_SOURCE_PRODUCT, scout.config_id, enabled=False
        ):
            paused += 1
    if paused:
        logger.info("replay_vision.variant_analysis.scouts_paused", scanner_id=str(scanner.id), paused=paused)
    return paused


def _cited_ids(raw: Any) -> set[str]:
    if not isinstance(raw, dict):
        return set()
    return {
        str(observation_id)
        for items in raw.values()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict) and isinstance(item.get("example_observation_ids"), list)
        for observation_id in item["example_observation_ids"]
    }


def _counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, int) and value >= 0}


def _lines(raw: Any, cited_variants: dict[str, str]) -> dict[str, tuple[VariantAnalysisLine, ...]]:
    if not isinstance(raw, dict):
        return {}
    lines: dict[str, tuple[VariantAnalysisLine, ...]] = {}
    for variant, items in raw.items():
        if not isinstance(items, list):
            continue
        lines[str(variant)] = tuple(
            VariantAnalysisLine(
                theme=str(item["theme"])[:_THEME_CHARS],
                statement=str(item["statement"])[:_STATEMENT_CHARS],
                count=item["count"],
                example_observation_ids=tuple(
                    str(observation_id)
                    for observation_id in (item.get("example_observation_ids") or [])[:MAX_EXAMPLES_PER_LINE]
                    if cited_variants.get(str(observation_id)) == str(variant)
                ),
            )
            for item in items[:MAX_LINES_PER_VARIANT]
            if isinstance(item, dict)
            and isinstance(item.get("theme"), str)
            and isinstance(item.get("statement"), str)
            and isinstance(item.get("count"), int)
        )
    return lines


def _differences(raw: Any) -> tuple[VariantAnalysisDifference, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        VariantAnalysisDifference(
            theme=str(item["theme"])[:_THEME_CHARS],
            statement=str(item["statement"])[:_STATEMENT_CHARS],
            counts=_counts(item.get("counts")),
        )
        for item in raw[:MAX_DIFFERENCES]
        if isinstance(item, dict) and isinstance(item.get("theme"), str) and isinstance(item.get("statement"), str)
    )
