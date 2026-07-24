"""Shared helpers for flat data-warehouse signal emitters.

Most warehouse tables expose the record as flat top-level columns (an id, a title, an
optional body, and a few metadata fields). `make_flat_emitter` builds a standard emitter for
that shape so each source module stays a thin config declaration. Sources with nested JSON
columns (e.g. Jira's `fields`) still write a bespoke emitter — see `jira_issues.py`.
"""

import json
from collections.abc import Callable
from typing import Any

from structlog import get_logger

from products.signals.backend.emission.registry import SignalEmitterOutput

logger = get_logger(__name__)


def parse_json_list(raw: Any) -> list[Any]:
    """Warehouse array columns arrive as either a native list or a JSON-encoded string."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def make_flat_emitter(
    *,
    source_product: str,
    source_type: str,
    id_field: str,
    title_field: str,
    body_field: str | None = None,
    extra_fields: tuple[str, ...] = (),
    json_list_fields: tuple[str, ...] = (),
) -> Callable[[int, dict[str, Any]], SignalEmitterOutput | None]:
    """Build an emitter for a flat table: `id`+`title` required, optional `body` appended.

    Returns `None` (skip the record) when the title is empty — a record with no human-readable
    text can't produce a useful signal. Raises `ValueError` only when a required column is
    entirely absent from the row (a schema/query mismatch worth surfacing loudly).
    """

    def emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
        try:
            record_id = record[id_field]
            title = record[title_field]
        except KeyError as e:
            msg = f"{source_product} record missing required field {e}"
            logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not record_id or not title:
            logger.info(
                f"Ignoring {source_product} record with empty id or title",
                team_id=team_id,
                signals_type="data-import-signals",
            )
            return None
        body = record.get(body_field) if body_field else None
        description = f"{title}\n{body}" if body else str(title)
        return SignalEmitterOutput(
            source_product=source_product,
            source_type=source_type,
            source_id=str(record_id),
            description=description,
            weight=1.0,
            extra=_build_extra(record, extra_fields, json_list_fields),
        )

    return emitter


def _build_extra(
    record: dict[str, Any],
    extra_fields: tuple[str, ...],
    json_list_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Build a deterministic extra dict: every declared field is present, list fields are
    normalized to lists, and scalars are coerced to `str | None` so the payload validates
    stably regardless of the warehouse column's stored type (int vs string, etc.)."""
    extra: dict[str, Any] = {}
    for field in extra_fields:
        if field in json_list_fields:
            extra[field] = parse_json_list(record.get(field))
        else:
            value = record.get(field)
            extra[field] = None if value is None else str(value)
    return extra
