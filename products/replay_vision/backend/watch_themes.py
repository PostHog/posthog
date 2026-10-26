"""Themes: clusters of a scanner's issue observations, each named as a search the Search tab suggests.

The embedding consumer hands every ranked observation to `assign_theme`. An issue observation joins the nearest
theme of its scanner, or starts one when none is close. Vectors are compared with the scanner's mean taken out,
because every observation of one scanner shares the wording of its question and would otherwise look alike.
A theme is named by a small model when it reaches a few members and renamed each time it doubles, so model calls
follow new findings rather than a schedule.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Func, JSONField, Value

import numpy as np
import structlog
from asgiref.sync import sync_to_async
from google.genai import types
from pydantic import BaseModel, Field

from posthog.dataclasses import frozen

from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.distinct_ids import replay_vision_distinct_id
from products.replay_vision.backend.gemini_client import AI_PRODUCT, replay_gemini_client
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import PromptValence, ReplayScanner, ScannerType
from products.replay_vision.backend.models.replay_scanner_theme import ReplayScannerTheme, ReplayScannerThemeCenter
from products.replay_vision.backend.observation_formatting import explanation_text
from products.replay_vision.backend.watch_rank import ISSUE_CATEGORIES, current_rank

logger = structlog.get_logger(__name__)

# text-embedding-3 vectors keep their meaning when cut short and renormalised, and a short one keeps each
# scanner's themes small enough to read on every observation.
THEME_DIMENSIONS = 512
# Centred similarity at which an observation joins a theme rather than starting one.
THEME_MIN_SIMILARITY = 0.40
# A young scanner's mean is mostly its few observations, so taking it out leaves noise. Until the centre has this
# many members, themes compare plain vectors at a plain similarity.
THEME_CENTRE_MIN_MEMBERS = 50
THEME_MIN_RAW_SIMILARITY = 0.85
# A theme with no new member for this long no longer takes members or counts as a suggestion.
THEME_ACTIVE_WINDOW = timedelta(days=30)
THEME_NAME_SAMPLES = 8
THEME_NAMING_DAILY_CAP = 100
MAX_THEME_LABEL_WORDS = 10
_THEME_MODEL = "gemini-3.5-flash-lite"
_SAMPLE_CHARS = 400
_IDENTIFIER = re.compile(r"https?://|www\.|@")

_NAMING_PROMPT = """You name a theme for a semantic search over AI-written observations of session recordings. \
The observations below come from one scanner, an AI check that looks for a specific thing in each session, and \
an embedding model grouped them because they describe the same kind of situation.

Write one search query that finds this theme: what these sessions have in common, phrased the way a person \
would describe what they are looking for (e.g. "coupon rejected at checkout", "gave up during signup").

Rules:
- 3 to 8 words, lowercase, no trailing punctuation.
- Name the shared situation, not one session's details. Prefer concrete product situations over generic \
phrases like "frustrated users".
- Never include names, emails, ids, URLs, or any other identifier from the observations.
- Return an empty query when the observations share no clear situation.

Scanner: {scanner_name}
Scanner instructions: {scanner_prompt}

Observations:
{samples}"""


class _ThemeName(BaseModel):
    query: str = Field(description="One search query for the shared theme, or an empty string.")


@frozen
class ThemeAssignment:
    theme_id: uuid.UUID
    name_due: bool


def theme_vector(vector: list[float] | np.ndarray) -> np.ndarray:
    head = np.zeros(THEME_DIMENSIONS, dtype=np.float32)
    values = np.asarray(vector[:THEME_DIMENSIONS], dtype=np.float32)
    head[: len(values)] = values
    return _unit(head)


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _pack(vector: np.ndarray) -> bytes:
    return vector.astype(np.float32).tobytes()


def _unpack(data: bytes | memoryview) -> np.ndarray:
    return np.frombuffer(bytes(data), dtype=np.float32)


def belongs_in_theme(*, category: str, scanner_type: str, valence: str, output: dict[str, Any]) -> bool:
    """An issue observation, and for a monitor with a known valence only the answer the team looks for, so a
    monitor's many reasons why nothing went wrong never become a suggestion."""
    if category not in ISSUE_CATEGORIES:
        return False
    if scanner_type == ScannerType.MONITOR:
        verdict = output.get("verdict")
        if valence == PromptValence.BAD:
            return verdict == "yes"
        if valence == PromptValence.GOOD:
            return verdict == "no"
    return True


def assign_theme(
    *, team_id: int, scanner_id: str, observation_id: str, vector: list[float], now: datetime
) -> ThemeAssignment | None:
    """Put one ranked observation in its scanner's nearest theme, or start a theme for it.

    None when the observation is not an issue, already has a theme, or is gone. The scanner's centre row is locked
    for the whole assignment, so two observations of one scanner never race on its themes, and a redelivered
    message finds its theme already written.
    """
    scanner = (
        ReplayScanner.objects.filter(team_id=team_id, id=scanner_id).values("scanner_type", "prompt_valence").first()
    )
    if scanner is None:
        return None
    with transaction.atomic():
        center, _ = (
            ReplayScannerThemeCenter.objects.for_team(team_id)
            .select_for_update()
            .get_or_create(
                scanner_id=scanner_id,
                defaults={"team_id": team_id, "vector_sum": _pack(np.zeros(THEME_DIMENSIONS, dtype=np.float32))},
            )
        )
        row = (
            ReplayObservation.objects.filter(team_id=team_id, id=observation_id)
            .values("watch_rank", "scanner_result")
            .first()
        )
        if row is None:
            return None
        rank = current_rank({"watch_rank": row["watch_rank"]})
        if rank is None or rank.get("theme"):
            return None
        output = (row["scanner_result"] or {}).get("model_output") or {}
        if not belongs_in_theme(
            category=rank["category"],
            scanner_type=scanner["scanner_type"],
            valence=scanner["prompt_valence"],
            output=output,
        ):
            return None

        v = theme_vector(vector)
        center_sum = _unpack(center.vector_sum) + v
        centring = center.member_count >= THEME_CENTRE_MIN_MEMBERS
        mean = center_sum / (center.member_count + 1) if centring else np.zeros_like(v)
        themes = list(
            ReplayScannerTheme.objects.for_team(team_id)
            .filter(scanner_id=scanner_id, last_member_at__gte=now - THEME_ACTIVE_WINDOW)
            .only("id", "vector_sum", "member_count", "name_at")
        )
        theme = _nearest_theme(themes, v, mean, THEME_MIN_SIMILARITY if centring else THEME_MIN_RAW_SIMILARITY)
        if theme is None:
            theme = ReplayScannerTheme.objects.for_team(team_id).create(
                team_id=team_id, scanner_id=scanner_id, vector_sum=_pack(v), member_count=1, last_member_at=now
            )
        else:
            theme.vector_sum = _pack(_unpack(theme.vector_sum) + v)
            theme.member_count += 1
            theme.last_member_at = now
            theme.save(update_fields=["vector_sum", "member_count", "last_member_at"])
        center.vector_sum = _pack(center_sum)
        center.member_count += 1
        center.save(update_fields=["vector_sum", "member_count"])
        ReplayObservation.objects.filter(team_id=team_id, id=observation_id).update(
            watch_rank=Func(
                F("watch_rank"),
                Value("{theme}"),
                Value(str(theme.id), output_field=JSONField()),
                function="jsonb_set",
                output_field=JSONField(),
            )
        )
    return ThemeAssignment(theme_id=theme.id, name_due=theme.member_count >= theme.name_at)


def _nearest_theme(
    themes: list[ReplayScannerTheme], vector: np.ndarray, mean: np.ndarray, threshold: float
) -> ReplayScannerTheme | None:
    """The theme whose mean is closest to the vector once the scanner's mean is taken out of both."""
    if not themes:
        return None
    centroids = np.stack([_unit(_unpack(t.vector_sum) / t.member_count - mean) for t in themes])
    similarities = centroids @ _unit(vector - mean)
    best = int(np.argmax(similarities))
    return themes[best] if similarities[best] >= threshold else None


def _claim_naming(team_id: int, theme_id: uuid.UUID) -> bool:
    """Move the theme's next naming to double its size, and say whether this caller won the right to name it now."""
    return bool(
        ReplayScannerTheme.objects.for_team(team_id)
        .filter(id=theme_id, member_count__gte=F("name_at"))
        .update(name_at=F("member_count") * 2)
    )


def _take_naming_budget(team_id: int, now: datetime) -> bool:
    key = f"replay_vision:theme_naming:{team_id}:{now:%Y-%m-%d}"
    cache.add(key, 0, timeout=2 * 24 * 3600)
    return cache.incr(key) <= THEME_NAMING_DAILY_CAP


def _naming_context(team_id: int, theme_id: uuid.UUID) -> tuple[ReplayScanner, list[str]] | None:
    theme = ReplayScannerTheme.objects.for_team(team_id).filter(id=theme_id).select_related("scanner").first()
    if theme is None:
        return None
    rows = (
        ReplayObservation.objects.filter(team_id=team_id, scanner_id=theme.scanner_id, watch_rank__theme=str(theme_id))
        .order_by("-created_at")
        .values_list("scanner_result", flat=True)[:THEME_NAME_SAMPLES]
    )
    samples = [
        text[:_SAMPLE_CHARS] for result in rows if (text := explanation_text((result or {}).get("model_output") or {}))
    ]
    return theme.scanner, samples


def _save_label(team_id: int, theme_id: uuid.UUID, label: str, now: datetime) -> None:
    ReplayScannerTheme.objects.for_team(team_id).filter(id=theme_id).update(label=label, named_at=now)


def finalize_label(raw: str) -> str:
    """The model's query in the shape a suggestion takes, or empty when it breaks the prompt's rules."""
    query = " ".join(raw.split()).strip().rstrip(".!?").lower()
    if not query or len(query.split()) > MAX_THEME_LABEL_WORDS or _IDENTIFIER.search(query):
        return ""
    return query[:128]


async def name_theme(team_id: int, theme_id: uuid.UUID, now: datetime) -> str | None:
    """Name a theme that reached its naming size. None when another caller claimed it, or nothing could be named."""
    if not await sync_to_async(_claim_naming)(team_id, theme_id):
        return None
    if not await sync_to_async(is_ai_data_processing_approved)(team_id):
        return None
    if not await sync_to_async(_take_naming_budget)(team_id, now):
        logger.info("replay_vision.watch_themes.naming_budget_spent", team_id=team_id)
        return None
    context = await sync_to_async(_naming_context)(team_id, theme_id)
    if context is None or not context[1]:
        return None
    scanner, samples = context
    prompt = (scanner.scanner_config or {}).get("prompt") if isinstance(scanner.scanner_config, dict) else None
    client = await replay_gemini_client(team_id, properties={"ai_product": AI_PRODUCT, "feature": "name_search_theme"})
    try:
        response = await client.models.generate_content(
            model=_THEME_MODEL,
            contents=_NAMING_PROMPT.format(
                scanner_name=scanner.name,
                scanner_prompt=(prompt or "")[:600],
                samples="\n".join(f"- {sample}" for sample in samples),
            ),
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=_ThemeName),
            posthog_distinct_id=replay_vision_distinct_id(team_id),
            posthog_trace_id=str(uuid.uuid4()),
            posthog_properties={"$ai_span_name": "name_search_theme", "team_id": team_id},
            posthog_groups={"project": str(team_id)},
        )
    finally:
        await client.aclose()
    label = finalize_label(_ThemeName.model_validate_json(response.text or "{}").query)
    if not label:
        return None
    await sync_to_async(_save_label)(team_id, theme_id, label, now)
    return label
