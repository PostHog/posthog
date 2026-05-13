"""Celery tasks for founder_mode.

Three async tasks live here, one per stage that needs LLM work:
- `run_validation_task` (stage 2, two-pass Gemini with grounded search)
- `run_gtm_task` (stage 3, OpenAI strict-JSON for launch playbook)
- `run_landing_page_task` (stage 4, single-pass Gemini for the build spec)

All three follow the same shape — write a `running` envelope → call the service → write
`completed` or `failed` back to the stage's JSON column. Tasks are the sole writers to
their respective columns during a run.

Architectural note: skipping the facade for now since no other product consumes founder_mode.
Tasks call logic/ directly. Reintroduce a facade once a cross-product consumer appears.
"""

import os
from datetime import UTC, datetime
from typing import Any, cast

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, Field

from posthog.models.user import User

from products.founder_mode.backend.logic.hashing import ideation_hash
from products.founder_mode.backend.logic.landing_page.service import generate_landing_page
from products.founder_mode.backend.logic.validation.service import run_validation
from products.founder_mode.backend.models import FounderProject

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@shared_task(ignore_result=True)
def run_validation_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Run the validation flow for a FounderProject and write the result back to its `validation` JSON.

    The task is fail-tolerant: any exception from the service is captured into the column
    so the frontend can render a failed state instead of polling forever.

    Writes `current_pass` between Gemini calls so the frontend can render real staged
    progress instead of estimating from elapsed time.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping validation, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to run validation as", project_id=founder_project_id)
        return

    snapshot_hash = ideation_hash(project.ideation)
    started_at = _now_iso()

    project.validation = {
        "status": "running",
        "current_pass": "research",
        "started_at": started_at,
        "ideation_hash": snapshot_hash,
        "report": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])

    def on_pass_change(pass_name: str) -> None:
        # Patch only `current_pass` — the surrounding envelope (started_at, status, hash) is
        # immutable for the duration of this task, so we splat to preserve it.
        project.validation = {**project.validation, "current_pass": pass_name}
        project.save(update_fields=["validation", "updated_at"])

    try:
        report, trace_id = run_validation(
            ideation_payload=project.ideation,
            team=project.team,
            user=user,
            on_pass_change=on_pass_change,
        )
    except Exception as exc:
        logger.exception("Validation run failed", project_id=founder_project_id)
        project.validation = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "ideation_hash": snapshot_hash,
            "report": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["validation", "updated_at"])
        return

    project.validation = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "ideation_hash": snapshot_hash,
        "report": report.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["validation", "updated_at"])


# --- GTM task (stage 3) ---


class SocialPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(description="Platform: 'linkedin', 'twitter', 'reddit', 'indie_hackers', or 'hacker_news'")
    content: str = Field(description="The full post text, ready to copy-paste and publish")
    tips: str = Field(description="Timing/format tips for this specific post")


class LaunchStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the action")
    description: str = Field(description="What to do and why it matters")
    channel: str = Field(description="Where this happens (e.g. 'Product Hunt', 'LinkedIn', 'Twitter/X', 'Reddit')")
    timeline: str = Field(description="When to do this relative to launch day (e.g. 'D-7', 'Launch day', 'D+1')")
    ready_to_use_content: list[SocialPost] = Field(description="Pre-written posts/content for this step")


class GTMStrategyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_summary: str = Field(description="2-3 sentence overview of the launch strategy")
    target_communities: list[str] = Field(description="Specific communities where the target audience hangs out")
    steps: list[LaunchStep] = Field(description="Ordered list of launch actions")


GTM_SYSTEM_PROMPT = """You are an expert startup launch strategist.
The user already has an MVP built. Your job is to create a concrete, manual launch playbook
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
Include 5-8 steps total."""

GTM_TIMEOUT = 90


async def _call_openai_gtm(product_description: str) -> GTMStrategyResult:
    client = AsyncOpenAI(base_url=settings.OPENAI_BASE_URL, timeout=GTM_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": GTM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Generate a go-to-market strategy for the following product:\n\n{product_description}",
        },
    ]

    response = await client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        response_format=cast(
            Any,
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "gtm_strategy_response",
                    "strict": True,
                    "schema": GTMStrategyResult.model_json_schema(),
                },
            },
        ),
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned empty response")
    return GTMStrategyResult.model_validate_json(content)


@shared_task(ignore_result=True)
def run_gtm_task(founder_project_id: str, product_description: str) -> None:
    """Generate a GTM launch plan via OpenAI and write the result to FounderProject.gtm."""
    project = FounderProject.objects.get(id=founder_project_id)

    if not os.getenv("OPENAI_API_KEY"):
        project.gtm = {"status": "failed", "result": None, "error": "OpenAI API key not configured"}
        project.save(update_fields=["gtm", "updated_at"])
        return

    project.gtm = {"status": "running", "result": None, "error": ""}
    project.save(update_fields=["gtm", "updated_at"])

    try:
        result = async_to_sync(_call_openai_gtm)(product_description)
    except Exception as exc:
        logger.exception("GTM generation failed", project_id=founder_project_id)
        project.gtm = {"status": "failed", "result": None, "error": str(exc)}
        project.save(update_fields=["gtm", "updated_at"])
        return

    project.gtm = {"status": "completed", "result": result.model_dump(), "error": ""}
    project.save(update_fields=["gtm", "updated_at"])


# --- Landing-page build-spec task (stage 4) ---


@shared_task(ignore_result=True)
def run_landing_page_task(founder_project_id: str, user_id: int | None = None) -> None:
    """Generate a landing page from the project's accumulated state and write it to `mvp`.

    Same fail-tolerant pattern as validation: exceptions are captured into the column so the
    frontend renders a failed state instead of polling forever. Single Gemini pass — no
    `current_pass` field needed.
    """
    project = FounderProject.objects.select_related("team").get(id=founder_project_id)

    if not project.ideation:
        logger.warning("Skipping landing page, no ideation set", project_id=founder_project_id)
        return

    user = User.objects.filter(id=user_id).first() if user_id else project.created_by
    if user is None:
        logger.warning("No user to generate landing page as", project_id=founder_project_id)
        return

    started_at = _now_iso()
    project.mvp = {
        "status": "running",
        "started_at": started_at,
        "page": None,
        "trace_id": None,
        "error": "",
    }
    project.save(update_fields=["mvp", "updated_at"])

    try:
        page, trace_id = generate_landing_page(
            project_name=project.name,
            ideation=project.ideation,
            validation=project.validation or {},
            gtm=project.gtm or {},
            team=project.team,
            user=user,
        )
    except Exception as exc:
        logger.exception("Landing page generation failed", project_id=founder_project_id)
        project.mvp = {
            "status": "failed",
            "started_at": started_at,
            "failed_at": _now_iso(),
            "page": None,
            "trace_id": None,
            "error": str(exc),
        }
        project.save(update_fields=["mvp", "updated_at"])
        return

    project.mvp = {
        "status": "completed",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "page": page.model_dump(),
        "trace_id": trace_id,
        "error": "",
    }
    project.save(update_fields=["mvp", "updated_at"])
