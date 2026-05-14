"""Stage-4 MVP happy-path generator.

Single Gemini call. Reads ideation + validation + gtm and produces a "smallest credible thing"
brief: a 3-7 step happy path + must-haves + explicitly excluded features. The prompt here is
deliberately a placeholder — the content shape and tone will be tuned once stage 4 has a UI.
"""

import json
import uuid
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from rest_framework import exceptions

from posthog.models.team.team import Team
from posthog.models.user import User

from .schemas import MVPHappyPath

logger = structlog.get_logger(__name__)

MVP_MODEL = "gemini-2.5-flash"

# PLACEHOLDER PROMPT — tune once we know what stage 4 actually surfaces to the founder.
SYSTEM_PROMPT = """You are a pragmatic product strategist helping a founder cut a v1 MVP down to the smallest credible thing.

You will receive: `ideation`, `validation`, `gtm`. Use them to ground the MVP — but be aggressive about cutting scope.

Produce an `MVPHappyPath` covering:
- `one_liner`: one sentence, no marketing language. What the product does end-to-end.
- `core_flow`: 3-7 numbered steps describing the happy path from first touch to value delivered. For each step state the user action, the system response, and a concrete success signal.
- `must_haves`: features that MUST ship in v1 for the happy path to work. If a feature isn't load-bearing for the flow above, it's not a must-have.
- `deliberately_excluded`: things that DO NOT belong in v1. Each entry has a one-line reason. Be opinionated — this list should be longer than the must-haves list. Cuts that show good taste: auth (use email magic link or a single SSO instead of full account), settings/preferences, mobile-responsive (desktop-only is fine for many B2B MVPs), notifications, billing UI (handle invoices manually), admin panel.

Rules:
- If a step in `core_flow` requires a feature not in `must_haves`, you've gotten the scope wrong — narrow it.
- No "nice to have" — that's `deliberately_excluded` with the reason "save for v2 after we have signal".
- No "AI-powered X" must-have unless the validation report says the wedge is the AI itself.

This is the smallest thing that proves the wedge from validation. Not the dream product."""


def _create_client() -> Any:
    """PostHog-wrapped Gemini client."""
    if settings.DEBUG and posthoganalytics.disabled:
        posthoganalytics.disabled = False
        if not posthoganalytics.host:
            posthoganalytics.host = settings.SITE_URL

    posthog_client = posthoganalytics.default_client
    if not posthog_client:
        logger.warning("PostHog default_client not available, LLM analytics will not be tracked")

    return genai.Client(api_key=settings.GEMINI_API_KEY, posthog_client=posthog_client)


def _format_payload(*, ideation: dict[str, Any], validation: dict[str, Any], gtm: dict[str, Any]) -> str:
    """Serialize upstream state as JSON for the model."""
    validation_report = validation.get("report") if isinstance(validation, dict) else None
    gtm_result = gtm.get("result") if isinstance(gtm, dict) else None
    return json.dumps(
        {
            "ideation": ideation,
            "validation": validation_report or {},
            "gtm": gtm_result or {},
        },
        indent=2,
    )


def generate_mvp_happy_path(
    *,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    gtm: dict[str, Any],
    team: Team,
    user: User,
) -> tuple[MVPHappyPath, str]:
    """Run the synthesis pass. Returns (spec, trace_id). Caller owns persistence."""
    client = _create_client()
    trace_id = str(uuid.uuid4())

    config = GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=MVPHappyPath.model_json_schema(),
        temperature=0.4,
    )

    response = client.models.generate_content(
        model=MVP_MODEL,
        contents=_format_payload(ideation=ideation, validation=validation, gtm=gtm),
        config=config,
        posthog_distinct_id=user.distinct_id or "",
        posthog_trace_id=trace_id,
        posthog_properties={"feature": "cofounder_mvp_happy_path"},
        posthog_groups={"project": str(team.id)},
    )

    if not response.text:
        raise exceptions.ValidationError("Gemini MVP happy path generation returned empty response")

    return MVPHappyPath.model_validate_json(response.text), trace_id
