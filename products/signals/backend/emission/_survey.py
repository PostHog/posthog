"""Shared helpers for survey tools that store answers in a JSON column.

Each source module passes an extractor that turns its own JSON shape into `SurveyAnswer`
items. `make_survey_emitter` keeps only free-text answers and returns `None` (skip) for a
response that has none. Choice, rating, email, phone, contact and file answers never reach
the description, and the helpers never read respondent identity.
"""

import re
import json
from collections.abc import Callable, Iterable
from typing import Any

from structlog import get_logger

from posthog.dataclasses import frozen

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission.registry import SignalEmitterOutput

logger = get_logger(__name__)

MAX_DESCRIPTION_CHARS = 4000

# Answer kinds, lowercased with punctuation removed, that hold typed-in prose.
FREE_TEXT_KINDS = frozenset(
    {
        "text",
        "shorttext",
        "longtext",
        "openended",
        "opentext",
        "essay",
        "comment",
        "comments",
        "textarea",
        "textinput",
        "multilinetext",
        "multilineinput",
        "freetext",
        "paragraph",
    }
)

# Delimiter-exclusive classes keep the match linear-time on long answers full of "@" and ".".
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$")
_PHONE_RE = re.compile(r"^[+\d][\d\s().-]{6,}$")
_FALSE_FLAGS = (False, 0, "0", "false", "False")
# Keys or labels of fields that collect respondent identity rather than feedback.
_CONTACT_KEY_RE = re.compile(r"e-?mail|phone|name|contact|address|^ip$", re.IGNORECASE)


@frozen
class SurveyAnswer:
    kind: str | None
    text: Any
    label: str | None = None


def parse_json(raw: Any) -> Any:
    """Warehouse JSON columns arrive as either a native value or a JSON-encoded string."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return raw


def is_free_text_kind(kind: Any) -> bool:
    if not isinstance(kind, str):
        return False
    return re.sub(r"[^a-z]", "", kind.lower()) in FREE_TEXT_KINDS


def is_explicitly_false(value: Any) -> bool:
    """True only for a known false flag, so a missing or odd-typed column keeps the record."""
    return value in _FALSE_FLAGS


def looks_like_contact_key(key: Any) -> bool:
    return isinstance(key, str) and bool(_CONTACT_KEY_RE.search(key))


def looks_like_contact(text: str) -> bool:
    return bool(_EMAIL_RE.match(text) or _PHONE_RE.match(text))


def free_text_description(answers: Iterable[SurveyAnswer]) -> str | None:
    lines: list[str] = []
    for answer in answers:
        if not is_free_text_kind(answer.kind) or not isinstance(answer.text, str):
            continue
        text = answer.text.strip()
        if not text or looks_like_contact(text):
            continue
        lines.append(f"{answer.label}: {text}" if answer.label else text)
    if not lines:
        return None
    return "\n".join(lines)[:MAX_DESCRIPTION_CHARS]


def make_survey_emitter(
    *,
    source_product: str,
    source_type: str,
    build_source_id: Callable[[dict[str, Any]], Any],
    extract_answers: Callable[[dict[str, Any]], Iterable[SurveyAnswer]],
    extra_fields: tuple[str, ...] = (),
    json_list_fields: tuple[str, ...] = (),
    is_eligible: Callable[[dict[str, Any]], bool] | None = None,
    transform_extra: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[[int, dict[str, Any]], SignalEmitterOutput | None]:
    """Build an emitter for a survey response table.

    `build_source_id` may raise `KeyError` when a required column is absent from the row, which
    surfaces as a `ValueError` (a query/schema mismatch). An empty id, an ineligible response or a
    response without free text returns `None`.
    """

    def emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
        try:
            source_id = build_source_id(record)
        except KeyError as e:
            msg = f"{source_product} record missing required field {e}"
            logger.exception(msg, record_keys=list(record), team_id=team_id, signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not source_id:
            return None
        if is_eligible is not None and not is_eligible(record):
            return None
        description = free_text_description(extract_answers(record))
        if description is None:
            logger.info(
                f"Ignoring {source_product} response without free-text answers",
                team_id=team_id,
                signals_type="data-import-signals",
            )
            return None
        extra = build_extra(record, extra_fields, json_list_fields)
        return SignalEmitterOutput(
            source_product=source_product,
            source_type=source_type,
            source_id=str(source_id),
            description=description,
            weight=1.0,
            extra=transform_extra(extra) if transform_extra else extra,
        )

    return emitter
