"""Search themes: broad clusters of a scanner's issue observations, each named as a search the Search tab suggests.

An issue observation joins the closest active theme of its scanner, or starts one when none is close. A theme is
named by a small model when it reaches a few members and renamed each time it doubles, so model calls follow new
findings rather than a schedule.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import F

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
from products.replay_vision.backend.models.replay_scanner_semantics import ReplayScannerSearchTheme
from products.replay_vision.backend.observation_formatting import explanation_text
from products.replay_vision.backend.semantic_space import (
    SEMANTIC_DIMENSIONS,
    SemanticSpace,
    nearest_cluster,
    pack,
    unpack,
)
from products.replay_vision.backend.watch_rank import ISSUE_CATEGORIES

logger = structlog.get_logger(__name__)

THEME_MIN_SIMILARITY = 0.40
THEME_MIN_RAW_SIMILARITY = 0.85
# A theme with no new member for this long no longer takes members or counts as a suggestion.
THEME_ACTIVE_WINDOW = timedelta(days=30)
# Bounds the themes one assignment reads while it holds the scanner's lock.
MAX_ACTIVE_THEMES = 2_000
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


def assign_theme(*, team_id: int, scanner_id: str, space: SemanticSpace, now: datetime) -> ThemeAssignment:
    """Put one observation in its scanner's closest active theme, or start a theme. Call under the centre lock."""
    themes = list(
        ReplayScannerSearchTheme.objects.for_team(team_id)
        .filter(scanner_id=scanner_id, last_member_at__gte=now - THEME_ACTIVE_WINDOW)
        .order_by("-last_member_at")
        .only("id", "vector_sum", "member_count", "rename_at_member_count", "last_member_at")[:MAX_ACTIVE_THEMES]
    )
    best = nearest_cluster(
        np.array([unpack(theme.vector_sum) for theme in themes], dtype=np.float32).reshape(-1, SEMANTIC_DIMENSIONS),
        np.array([theme.member_count for theme in themes], dtype=np.float32),
        space,
        THEME_MIN_SIMILARITY,
        THEME_MIN_RAW_SIMILARITY,
    )
    if best is None:
        theme = ReplayScannerSearchTheme.objects.for_team(team_id).create(
            team_id=team_id, scanner_id=scanner_id, vector_sum=pack(space.vector), member_count=1, last_member_at=now
        )
    else:
        theme = themes[best]
        theme.vector_sum = pack(unpack(theme.vector_sum) + space.vector)
        theme.member_count += 1
        # The backfill replays old rows while the consumer adds new ones, so the latest member time never moves back.
        theme.last_member_at = max(theme.last_member_at, now)
        theme.save(update_fields=["vector_sum", "member_count", "last_member_at"])
    return ThemeAssignment(theme_id=theme.id, name_due=theme.member_count >= theme.rename_at_member_count)


def _claim_naming(team_id: int, theme_id: uuid.UUID) -> bool:
    """Move the theme's next naming to double its size, and say whether this caller won the right to name it now."""
    return bool(
        ReplayScannerSearchTheme.objects.for_team(team_id)
        .filter(id=theme_id, member_count__gte=F("rename_at_member_count"))
        .update(rename_at_member_count=F("member_count") * 2)
    )


def _take_naming_budget(team_id: int, now: datetime) -> bool:
    key = f"replay_vision:theme_naming:{team_id}:{now:%Y-%m-%d}"
    cache.add(key, 0, timeout=2 * 24 * 3600)
    return cache.incr(key) <= THEME_NAMING_DAILY_CAP


def _naming_context(team_id: int, theme_id: uuid.UUID) -> tuple[ReplayScanner, list[str]] | None:
    theme = ReplayScannerSearchTheme.objects.for_team(team_id).filter(id=theme_id).select_related("scanner").first()
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


def _save_name(team_id: int, theme_id: uuid.UUID, name: str) -> None:
    ReplayScannerSearchTheme.objects.for_team(team_id).filter(id=theme_id).update(name=name)


def finalize_label(raw: str) -> str:
    """The model's query in the shape a suggestion takes, or empty when it breaks the prompt's rules."""
    query = " ".join(raw.split()).strip().rstrip(".!?").lower()
    if not query or len(query.split()) > MAX_THEME_LABEL_WORDS or _IDENTIFIER.search(query):
        return ""
    return query[:128]


async def name_theme(team_id: int, theme_id: uuid.UUID, now: datetime) -> str | None:
    """Name a theme that reached its naming size. None when another caller claimed it, or nothing could be named."""
    # Consent and budget come before the claim, so a theme that cannot be named now is tried again on its next member.
    if not await sync_to_async(is_ai_data_processing_approved)(team_id):
        return None
    if not await sync_to_async(_take_naming_budget)(team_id, now):
        logger.info("replay_vision.watch_themes.naming_budget_spent", team_id=team_id)
        return None
    if not await sync_to_async(_claim_naming)(team_id, theme_id):
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
    await sync_to_async(_save_name)(team_id, theme_id, label)
    return label
