"""Stage-5b practical launch playbook (under the marketing umbrella in the UI).

Single OpenAI gpt-4.1 call with strict JSON schema. Kept on OpenAI (vs Gemini for the other
stages) because the existing prompt is tuned against it; unifying providers can be a separate
follow-up. Reads the project's accumulated state (ideation + validation + gtm + mvp) so the
playbook reflects what's actually being launched — no fresh `product_description` input.
"""

import json
import uuid
from typing import Any, cast

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from posthog.models.team.team import Team
from posthog.models.user import User

from .schemas import PracticalStepsResult

logger = structlog.get_logger(__name__)

OPENAI_MODEL = "gpt-4.1"
OPENAI_TIMEOUT = 90

SYSTEM_PROMPT = """You are an expert startup launch strategist.
The founder already has an MVP built. Your job is to create a concrete, manual launch playbook
with ready-to-use content they can copy-paste and publish TODAY.

Focus ONLY on promotion and distribution — NOT on building, coding, or product development.

Your strategy should include:
- A Product Hunt launch plan (tagline, description, first comment, hunter outreach)
- LinkedIn posts (personal story angle, product announcement, lessons learned)
- Twitter/X threads (hook + thread structure, engagement bait)
- Reddit/community posts tailored to relevant subreddits
- Hacker News "Show HN" post if appropriate
- Indie Hackers or niche community posts

For each step, provide ACTUAL ready-to-publish content — full post text, not templates.
Make the content authentic, non-spammy, founder-voice, and optimized for each platform's algorithm.

Order steps chronologically: pre-launch buildup (D-7 to D-1), launch day, post-launch follow-up.
Include 5-8 steps total.

Ground every claim in the founder's actual project. The input JSON carries:
- `ideation` — what they're building (what, how, who, problem)
- `validation` — competitive landscape and verdict
- `gtm` — positioning, target segments, pricing, channels (may be empty if stage 3 hasn't run)
- `mvp` — what the v1 actually does (may be empty if stage 4 hasn't run)

Use the primary acquisition channel from `gtm` to decide which platforms to weight. If GTM is empty, default to Product Hunt + LinkedIn + Twitter as the baseline mix."""


def _format_payload(
    *,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    gtm: dict[str, Any],
    mvp: dict[str, Any],
) -> str:
    """Serialize the upstream project state into the user-prompt JSON."""
    return json.dumps(
        {
            "ideation": ideation,
            "validation": validation.get("report") if isinstance(validation, dict) else {},
            "gtm": gtm.get("result") if isinstance(gtm, dict) else {},
            "mvp": mvp.get("result") if isinstance(mvp, dict) else {},
        },
        indent=2,
    )


async def _call_openai(*, payload: str) -> PracticalStepsResult:
    client = AsyncOpenAI(base_url=settings.OPENAI_BASE_URL, timeout=OPENAI_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Generate a launch playbook for the following project:\n\n{payload}"},
    ]

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        response_format=cast(
            Any,
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "practical_steps_response",
                    "strict": True,
                    "schema": PracticalStepsResult.model_json_schema(),
                },
            },
        ),
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned empty response")
    return PracticalStepsResult.model_validate_json(content)


def generate_practical_steps(
    *,
    ideation: dict[str, Any],
    validation: dict[str, Any],
    gtm: dict[str, Any],
    mvp: dict[str, Any],
    team: Team,
    user: User,
) -> tuple[PracticalStepsResult, str]:
    """Run the launch playbook synthesis. Returns (result, trace_id). Caller owns persistence.

    `team` and `user` are accepted for signature parity with the Gemini-based services; the
    OpenAI client doesn't go through `posthoganalytics.ai.openai` today, so they aren't
    forwarded — observability gap to address when we unify LLM analytics here.
    """
    trace_id = str(uuid.uuid4())
    payload = _format_payload(ideation=ideation, validation=validation, gtm=gtm, mvp=mvp)
    result = async_to_sync(_call_openai)(payload=payload)
    return result, trace_id
