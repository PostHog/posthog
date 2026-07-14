"""Measure the recall gap in Pulse briefs: signals an LLM judge expects but the brief lacks.

Samples recent ready ProductBriefs that have sections, asks an LLM judge which signals a
product reviewer would expect from the brief's content, and reports which of those are
absent. This is a measurement tool for deciding whether a pre-agent query-expansion stage
is worth building — it does not change brief generation.

Usage:
    python manage.py pulse_measure_recall --team-id 2 --limit 20
"""

import asyncio
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async

from products.pulse.backend.models import ProductBrief

from ee.hogai.llm import MaxChatOpenAI

_JUDGE_MODEL = "gpt-4.1"
_LLM_TIMEOUT_SECONDS = 60
_DEFAULT_LIMIT = 20

_JUDGE_PROMPT = """You are a senior product reviewer auditing a generated product brief for completeness.

Below are the brief's sections (title and markdown body). List the signals a thorough product
reviewer would expect to see addressed, given what's already discussed, then say which of those
expected signals are NOT covered anywhere in the brief's sections.

Brief sections:
{sections_block}
"""


class MissedSignals(BaseModel):
    expected: list[str] = Field(description="Signals a product reviewer would expect this brief to address.")
    missing: list[str] = Field(description="Which of the expected signals are absent from the brief's sections.")


def _render_sections(sections: list[dict[str, Any]]) -> str:
    blocks = []
    for section in sections:
        title = section.get("title", "")
        markdown = section.get("markdown", "")
        blocks.append(f"- {title}\n  {markdown}")
    return "\n".join(blocks)


async def _judge_brief(brief: ProductBrief) -> MissedSignals:
    llm = MaxChatOpenAI(
        model=_JUDGE_MODEL,
        timeout=_LLM_TIMEOUT_SECONDS,
        max_retries=1,
        user=brief.created_by,
        team=brief.team,
        billable=True,
        posthog_properties={"ai_product": "pulse", "ai_feature": "measure_recall"},
    ).with_structured_output(MissedSignals, method="json_schema", include_raw=False)
    rendered = _JUDGE_PROMPT.format(sections_block=_render_sections(brief.sections))
    result = await database_sync_to_async(llm.invoke, thread_sensitive=False)([("system", rendered)])
    if not isinstance(result, MissedSignals):
        raise ValueError(f"LLM judge returned unexpected structured output type: {type(result).__name__}")
    return result


async def _measure(briefs: list[ProductBrief]) -> list[tuple[ProductBrief, MissedSignals]]:
    results = []
    for brief in briefs:
        judged = await _judge_brief(brief)
        results.append((brief, judged))
    return results


class Command(BaseCommand):
    help = "Sample recent Pulse briefs and measure the recall gap via an LLM judge."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to a single team.")
        parser.add_argument(
            "--limit", type=int, default=_DEFAULT_LIMIT, help="Max number of briefs to sample (default 20)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]
        limit: int = options["limit"]

        # select_related: team + created_by are read inside the async _measure loop (MaxChatOpenAI
        # needs both), so they must be eager-loaded or the lazy query trips SynchronousOnlyOperation.
        # created_by must be present — the LLM judge bills to a user; user-less (scheduled) briefs are skipped.
        briefs_qs = (
            ProductBrief.objects.unscoped()
            .select_related("team", "created_by")
            .exclude(sections=[])
            .filter(created_by__isnull=False)
            .order_by("-created_at")
        )
        if team_id is not None:
            briefs_qs = briefs_qs.filter(team_id=team_id)
        briefs = list(briefs_qs[:limit])

        if not briefs:
            self.stdout.write("sampled=0 miss_rate=0.0")
            return

        results = asyncio.run(_measure(briefs))

        briefs_with_misses = 0
        for brief, judged in results:
            if judged.missing:
                briefs_with_misses += 1
            self.stdout.write(
                f"brief={brief.id} team={brief.team_id} expected={judged.expected} missing={judged.missing}"
            )

        miss_rate = briefs_with_misses / len(results)
        self.stdout.write(f"sampled={len(results)} miss_rate={miss_rate}")
