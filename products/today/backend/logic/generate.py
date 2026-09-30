"""The two generation steps. Each runs as its own Temporal activity and reads and writes the row."""

from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ..facade.enums import BriefingStatus, BriefingWriter
from ..models import DailyBriefing
from .candidates import SourceContext
from .checks import check_content
from .draft import build_draft
from .eligibility import is_enabled_for
from .fact_sheet import build_fact_sheet
from .ranking import rank_candidates, select
from .sources import collect_all, reports
from .writer import WriterError, write

logger = structlog.get_logger(__name__)

WRITER_ATTEMPTS = 2


def _load(team_id: int, briefing_id: str) -> tuple[DailyBriefing, Team, User]:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    team = Team.objects.select_related("organization").get(id=briefing.team_id)
    user = User.objects.get(id=briefing.user_id)
    return briefing, team, user


def collect_and_draft(*, team_id: int, briefing_id: str) -> bool:
    """Collect, rank and store the fact sheet and the draft.

    False when the person may not get a briefing. The flag can turn off after the row was created,
    so the row is deleted then: a briefing nobody can open is not worth keeping.
    """
    briefing, team, user = _load(team_id, briefing_id)
    if not is_enabled_for(user, team):
        briefing.delete()
        return False
    ctx = SourceContext(team=team, user=user, now=timezone.now())
    collected = collect_all(ctx)
    items = select(rank_candidates(collected.candidates))
    try:
        reports_count = reports.reports_for_me_count(ctx)
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
        reports_count = 0
    fact_sheet = build_fact_sheet(
        first_name=user.first_name,
        local_day=briefing.local_day,
        items=items,
        reports_for_me_count=reports_count,
        failed_sources=collected.failed_sources,
    )
    draft = build_draft(fact_sheet)
    briefing.facts = fact_sheet
    briefing.draft = draft
    briefing.content = draft
    briefing.writer = BriefingWriter.TEMPLATE
    briefing.status = BriefingStatus.WRITING
    briefing.save(update_fields=["facts", "draft", "content", "writer", "status"])
    return True


def write_and_check(*, team_id: int, briefing_id: str) -> None:
    """Replace the draft with the LLM text when it passes the checks; keep the draft otherwise."""
    briefing, team, user = _load(team_id, briefing_id)
    fact_sheet = briefing.facts
    if fact_sheet.get("items") and team.organization.is_ai_data_processing_approved:
        problems: list[str] | None = None
        for _ in range(WRITER_ATTEMPTS):
            try:
                content, cost = write(team=team, user=user, fact_sheet=fact_sheet, problems=problems)
            except WriterError as error:
                problems = [str(error)]
                continue
            except Exception as error:
                logger.exception("today_writer_failed", team_id=team.id)
                capture_exception(error, {"team_id": team.id, "product": "today"})
                briefing.error = f"writer failed: {error}"[:1000]
                break
            briefing.llm_cost_usd = (briefing.llm_cost_usd or 0) + cost
            problems = check_content(fact_sheet, content)
            if not problems:
                briefing.content = content
                briefing.writer = BriefingWriter.LLM
                briefing.error = None
                break
        if problems:
            briefing.error = ("checks failed: " + "; ".join(problems))[:1000]
    briefing.status = BriefingStatus.READY
    briefing.ready_at = timezone.now()
    briefing.save(update_fields=["content", "writer", "error", "llm_cost_usd", "status", "ready_at"])


def mark_failed(*, team_id: int, briefing_id: str, error: str) -> None:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    briefing.status = BriefingStatus.FAILED
    briefing.error = error[:1000]
    if briefing.draft and not briefing.content:
        briefing.content = briefing.draft
    briefing.save(update_fields=["status", "error", "content"])
