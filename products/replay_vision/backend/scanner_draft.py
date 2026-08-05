"""Draft a full scanner configuration from a user's stated goal.

The template picker asks "what do you want to accomplish?" and this turns the answer into a ready-to-review
scanner draft: the scanner type, a name, a description, and the type-specific config (prompt, tag vocabulary,
score scale, or summary length). The draft is grounded in the team's real product events and screens so the
prompt talks about THEIR product, then lands in the creation wizard where the user reviews and adjusts it.
Nothing is persisted here; the create endpoint re-validates everything on save.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from pydantic import BaseModel, Field

from posthog.models.team import Team
from posthog.models.user import User

from products.replay_vision.backend.tag_suggestions import _product_taxonomy
from products.replay_vision.backend.tags import slugify_tag

logger = structlog.get_logger(__name__)

# Interactive request path, but drafting a whole scanner well needs more model than the tag helper.
_DRAFT_MODEL = "gemini-3.6-flash"
_MODEL_CALL_TIMEOUT_MS = 90_000
_MAX_NAME_LENGTH = 255  # ReplayScanner.name column length
_MAX_DESCRIPTION_LENGTH = 1_000
_MAX_PROMPT_LENGTH = 20_000
_MAX_DRAFT_TAGS = 12
_DEFAULT_SCALE = (0, 10)


class DraftError(Exception):
    """Raised when the model call fails or returns nothing usable."""


class _LlmDraft(BaseModel):
    """The model's structured output: one drafted scanner."""

    scanner_type: Literal["monitor", "classifier", "scorer", "summarizer"] = Field(
        description="The scanner type that best fits the goal."
    )
    name: str = Field(description="Short scanner name (under 8 words), e.g. 'Checkout abandonment'.")
    description: str = Field(description="One sentence describing what the scanner looks for and why.")
    prompt: str = Field(description="The instruction the scanner follows while watching a single session recording.")
    tags: list[str] = Field(
        default_factory=list,
        description="Classifier only: 4-8 lowercase snake_case tags forming the vocabulary; empty otherwise.",
    )
    multi_label: bool = Field(default=False, description="Classifier only: whether a session can get multiple tags.")
    scale_min: int = Field(default=0, description="Scorer only: lowest score on the scale.")
    scale_max: int = Field(default=10, description="Scorer only: highest score on the scale.")
    scale_label: str | None = Field(
        default=None, description="Scorer only: one-word label for the dimension being scored, e.g. 'frustration'."
    )
    length: Literal["short", "medium", "long"] = Field(
        default="medium", description="Summarizer only: how long each summary should be."
    )


@dataclass(frozen=True, kw_only=True)
class ScannerDraft:
    """A normalized draft ready to seed the creation wizard's form."""

    name: str
    description: str
    scanner_type: str
    scanner_config: dict[str, Any]


_SYSTEM_PROMPT = """
You turn a PostHog user's goal into a draft Replay Vision scanner. A scanner watches individual session
recordings of the user's product and produces one observation per recording. There are four scanner types:

- monitor: answers a yes/no question about the session (e.g. "Did the user fail to complete checkout?").
  Best when the goal is detecting whether something specific happened.
- classifier: assigns the session one or more tags from a fixed vocabulary along a single dimension
  (e.g. primary user intent). Best when the goal is understanding the mix of behaviors or outcomes.
- scorer: rates the session on a numeric scale along a single dimension (e.g. frustration 0-10).
  Best when the goal is ranking sessions by intensity of something.
- summarizer: writes a free-text summary of the session. Best when the goal is broad ("what are users
  doing?", "give me an overview") and doesn't fit one question, dimension, or vocabulary.

Pick the single type that best fits the goal, then draft the scanner:
- name: short and specific, under 8 words.
- description: one sentence saying what the scanner looks for.
- prompt: a direct, specific instruction grounded in behavior observable in a recording. Reference the
  product's real screens and events where relevant so the scanner knows what to look at. Avoid vague
  adjectives, multi-part questions, and data the model cannot see in a recording (revenue, account tier).
  - monitor prompts state a yes/no question, what counts as a yes, and ask for a one-sentence reason.
  - classifier prompts describe the dimension to categorize by; do NOT list the tags in the prompt
    (the vocabulary is configured separately via `tags`).
  - scorer prompts describe what a low score versus a high score means; the numeric scale is configured
    separately via `scale_min`/`scale_max`.
  - summarizer prompts say what the summary should focus on.
- Fill only the fields relevant to the chosen type; leave the rest at their defaults.
- For classifiers: 4-8 lowercase snake_case tags that are distinct, non-overlapping categories along the
  dimension. No vague catch-alls ("other", "misc").
- Output strictly matches the provided JSON schema."""


def _build_user_content(goal: str, events: list[str], screens: list[str]) -> str:
    lines = [f"The user's goal:\n{goal.strip()}"]
    if events:
        lines.append("\nThe product's most active custom events (what users do here):\n- " + "\n- ".join(events))
    if screens:
        lines.append("\nScreens/paths sessions cover:\n- " + "\n- ".join(screens))
    return "\n".join(lines)


def draft_scanner_from_goal(*, team: Team, user: User, goal: str) -> ScannerDraft:
    """Ground the goal in the team's product taxonomy and synthesize one scanner draft.

    Raises DraftError on model failure."""
    taxonomy = _product_taxonomy(team)
    user_content = _build_user_content(goal, taxonomy.events, taxonomy.screens)
    parsed = _generate(user_content=user_content, team_id=team.id, distinct_id=str(user.uuid))
    return _finalize(parsed)


def _generate(*, user_content: str, team_id: int, distinct_id: str) -> _LlmDraft:
    api_key = settings.REPLAY_VISION_GEMINI_API_KEY or settings.GEMINI_API_KEY
    # Runs inline on the interactive request path, so a hung provider call must time out.
    try:
        client = genai.Client(
            api_key=api_key,
            posthog_client=posthoganalytics.default_client,
            http_options={"timeout": _MODEL_CALL_TIMEOUT_MS},
        )
    except Exception as e:
        # A missing or malformed API key raises at construction. Wrap it so the API returns
        # the friendly 503 instead of a 500.
        raise DraftError("model client unavailable") from e
    config = GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=_LlmDraft.model_json_schema(),
        temperature=0.3,
    )
    try:
        response = client.models.generate_content(
            model=_DRAFT_MODEL,
            contents=user_content,
            config=config,
            posthog_distinct_id=distinct_id,
            posthog_trace_id=str(uuid.uuid4()),
            posthog_properties={"ai_product": "replay_vision", "feature": "draft_scanner_from_goal"},
            posthog_groups={"project": str(team_id)},
        )
    except Exception as e:
        logger.exception("replay_vision.scanner_draft.generate_failed", team_id=team_id)
        raise DraftError("model call failed") from e

    if not response.text:
        raise DraftError("empty response")
    try:
        return _LlmDraft.model_validate_json(response.text)
    except Exception as e:
        raise DraftError("invalid response") from e


def _finalize(parsed: _LlmDraft) -> ScannerDraft:
    """Normalize the model output into a draft the wizard form (and later the create endpoint) will accept."""
    name = parsed.name.strip()[:_MAX_NAME_LENGTH]
    prompt = parsed.prompt.strip()[:_MAX_PROMPT_LENGTH]
    if not name or not prompt:
        raise DraftError("draft missing name or prompt")

    scanner_config: dict[str, Any] = {"prompt": prompt}
    if parsed.scanner_type == "classifier":
        # Order-preserving dedup of slugified tags, dropping anything that slugs to empty.
        tags = list(dict.fromkeys(s for t in parsed.tags if (s := slugify_tag(t))))[:_MAX_DRAFT_TAGS]
        scanner_config["tags"] = tags
        scanner_config["multi_label"] = parsed.multi_label
    elif parsed.scanner_type == "scorer":
        scale_min, scale_max = parsed.scale_min, parsed.scale_max
        if scale_min >= scale_max:
            scale_min, scale_max = _DEFAULT_SCALE
        scale: dict[str, Any] = {"min": scale_min, "max": scale_max}
        label = (parsed.scale_label or "").strip()
        if label:
            scale["label"] = label
        scanner_config["scale"] = scale
    elif parsed.scanner_type == "summarizer":
        scanner_config["length"] = parsed.length

    return ScannerDraft(
        name=name,
        description=parsed.description.strip()[:_MAX_DESCRIPTION_LENGTH],
        scanner_type=parsed.scanner_type,
        scanner_config=scanner_config,
    )
