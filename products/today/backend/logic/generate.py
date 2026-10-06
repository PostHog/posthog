"""Generating a briefing: PostHog picks the person's top reports, and one LLM call writes the text about them."""

from datetime import timedelta

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_openai_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.signals.backend.facade import api as signals

from ..facade.enums import BriefingStatus
from ..feature_flags import may_get_briefing
from ..models import DailyBriefing
from .briefings import recent_ready_briefings, store_briefing
from .content import BriefingContent
from .fact_sheet import FactSheet, fact_sheet_for_reports
from .llm_output import BriefingOutput, strict_schema, to_content
from .prompt import build_prompt

MODEL = "gpt-6-luna"
MAX_COMPLETION_TOKENS = 8192
MAX_ITEMS = 5
CALL_TIMEOUT = timedelta(minutes=2)
# One activity attempt: the reads, the LLM call and the write.
ATTEMPT_TIMEOUT = CALL_TIMEOUT + timedelta(minutes=1)
# Temporal retries the whole attempt, so the LLM client does not retry on its own.
ATTEMPTS = 3
RETRY_INTERVAL = timedelta(seconds=10)
# Every attempt at its budget plus the waits between them. The workflow enforces it, and the
# stuck sweep and the page's polling derive from it.
RUN_TIMEOUT = ATTEMPT_TIMEOUT * ATTEMPTS + timedelta(minutes=1)
# How many of the person's previous briefings the LLM sees, so it does not repeat itself.
RECENT_BRIEFINGS = 3


@frozen
class _PreparedRun:
    fact_sheet: FactSheet
    prompt: str
    distinct_id: str


def _prepare(team_id: int, briefing_id: str) -> _PreparedRun | None:
    """The items and the prompt, or None when the person may not get a briefing.

    Access, credits or the flag can go after the row was created, so the row is deleted then:
    a briefing nobody can open is not worth an LLM call. A failure to read the reports fails
    the attempt, because an empty list would tell the person that nothing needs them.
    """
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    team = Team.objects.select_related("organization").get(id=briefing.team_id)
    user = User.objects.get(id=briefing.user_id)
    if not may_get_briefing(user, team):
        briefing.delete()
        return None
    briefing.status = BriefingStatus.WRITING
    briefing.save(update_fields=["status"])
    # A P0 nobody owns belongs to the project, not to this person, and would sort above every
    # item that is actually theirs. It stays in the Inbox and in `open_reports_count`.
    reports = signals.reports_for_briefing(team_id=team.id, user_id=user.id, limit=MAX_ITEMS, include_unowned=False)
    fact_sheet = fact_sheet_for_reports(reports, team.id)
    summaries = {item.key: report.summary for item, report in zip(fact_sheet.items, reports, strict=True)}
    prompt = build_prompt(briefing, user, fact_sheet, summaries, recent_ready_briefings(briefing, RECENT_BRIEFINGS))
    return _PreparedRun(fact_sheet=fact_sheet, prompt=prompt, distinct_id=str(user.distinct_id))


async def _write_text(prepared: _PreparedRun, team_id: int) -> BriefingOutput:
    async with build_async_openai_client(
        product="posthog_ai",
        ai_product="today_briefing",
        distinct_id=prepared.distinct_id,
        properties={"team_id": str(team_id)},
    ).with_options(timeout=CALL_TIMEOUT.total_seconds(), max_retries=0) as client:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prepared.prompt}],
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "today_briefing", "strict": True, "schema": strict_schema(BriefingOutput)},
            },
            user=prepared.distinct_id,
        )
    # The gateway fronts several providers and does not honor a response format the same way on
    # every route, so a reply in a code fence still parses.
    return BriefingOutput.model_validate(extract_json_object(response.choices[0].message.content or "") or {})


def _store(team_id: int, briefing_id: str, fact_sheet: FactSheet, content: BriefingContent) -> None:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    store_briefing(briefing, fact_sheet, content)


async def write_briefing(*, team_id: int, briefing_id: str) -> None:
    """Write the briefing text in one LLM call and store it with the items PostHog picked.

    With no items there is no call, and the stored text is empty: the page then says that nothing
    needs the person.
    """
    prepared = await database_sync_to_async(_prepare, thread_sensitive=False)(team_id, briefing_id)
    if prepared is None:
        return
    if prepared.fact_sheet.items:
        content = to_content(await _write_text(prepared, team_id), prepared.fact_sheet)
    else:
        content = BriefingContent()
    await database_sync_to_async(_store, thread_sensitive=False)(team_id, briefing_id, prepared.fact_sheet, content)


def mark_failed(*, team_id: int, briefing_id: str, error: str) -> None:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    briefing.status = BriefingStatus.FAILED
    briefing.error = error[:1000]
    briefing.save(update_fields=["status", "error"])
