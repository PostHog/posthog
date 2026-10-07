from datetime import date, datetime
from enum import StrEnum

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from ..facade.enums import WarehouseSuggestionKind
from ..models import WarehouseSuggestionTeamConfig
from .candidates import CandidateContext, CandidateResult, evaluate_candidates
from .inventory import load_inventory
from .lifecycle import LifecycleResult, apply_run
from .reads import ReadWindow, TeamReads, read_team_reads
from .rules import RULES, EligibilityRules, Rules


class TeamRunStatus(StrEnum):
    DISABLED = "disabled"
    NOT_ELIGIBLE = "not_eligible"
    PROCESSED = "processed"


@frozen
class TeamRunResult:
    team_id: int
    status: TeamRunStatus
    drafts: int = 0
    lifecycle: LifecycleResult | None = None


def run_team(
    team_id: int, *, run_id: str, today: date, now: datetime | None = None, rules: Rules = RULES
) -> TeamRunResult:
    now = now or timezone.now()
    team = Team.objects.get(id=team_id)
    get_or_create_team_extension(team, WarehouseSuggestionTeamConfig)
    with transaction.atomic():
        config = WarehouseSuggestionTeamConfig.objects.select_for_update().get(team_id=team_id)
        if not config.enabled:
            return TeamRunResult(team_id=team_id, status=TeamRunStatus.DISABLED)
        reads = read_team_reads(team_id, ReadWindow.ending(today, rules), rules)
        eligible = is_eligible(reads, rules.eligibility)
        _record_run(config, reads, eligible=eligible, now=now)
        if not eligible:
            return TeamRunResult(team_id=team_id, status=TeamRunStatus.NOT_ELIGIBLE)
        context = build_context(team, reads, run_id=run_id, rules=rules)
        drafts = [draft for result in evaluate_candidates(context).values() for draft in result.drafts]
        lifecycle = apply_run(context, drafts, now, surface=config.paused_reason is None)
    return TeamRunResult(team_id=team_id, status=TeamRunStatus.PROCESSED, drafts=len(drafts), lifecycle=lifecycle)


def explain_team(
    team_id: int, *, today: date, rules: Rules = RULES
) -> tuple[CandidateContext, dict[WarehouseSuggestionKind, CandidateResult]]:
    team = Team.objects.get(id=team_id)
    reads = read_team_reads(team_id, ReadWindow.ending(today, rules), rules)
    context = build_context(team, reads, run_id="explain", rules=rules)
    return context, evaluate_candidates(context)


def is_eligible(reads: TeamReads, rules: EligibilityRules) -> bool:
    reads_views = reads.view_readers >= rules.min_view_readers and reads.view_reads >= rules.min_view_reads
    return reads_views or bool(reads.refreshes)


def build_context(team: Team, reads: TeamReads, *, run_id: str, rules: Rules) -> CandidateContext:
    return CandidateContext(team_id=team.pk, reads=reads, inventory=load_inventory(team), rules=rules, run_id=run_id)


def _record_run(config: WarehouseSuggestionTeamConfig, reads: TeamReads, *, eligible: bool, now: datetime) -> None:
    config.eligible = eligible
    config.days_with_data = reads.days_with_data
    config.last_run_at = now
    config.save(update_fields=["eligible", "days_with_data", "last_run_at"])
