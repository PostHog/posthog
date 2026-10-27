from collections import defaultdict
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from ..facade.contracts import SuggestionDraft
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus
from ..models import WarehouseSuggestion, WarehouseSuggestionTeamConfig
from .analytics import report_candidates
from .candidates.base import CandidateContext, CandidateResult
from .candidates.registry import evaluate_candidates
from .inventory import load_inventory
from .lifecycle import FLIP_KINDS, LifecycleResult, apply_run
from .reads import ReadWindow, RollupDays, TeamReads, read_rollup_days, read_team_reads
from .rules import RULES, EligibilityRules, Rules

MAINTAINED_STATUSES = (WarehouseSuggestionStatus.PROPOSED, WarehouseSuggestionStatus.ACCEPTED)


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
    team_id: int,
    *,
    run_id: str,
    today: date,
    rollup_days: RollupDays,
    now: datetime | None = None,
    rules: Rules = RULES,
) -> TeamRunResult:
    now = now or timezone.now()
    team = Team.objects.get(id=team_id)
    if not get_or_create_team_extension(team, WarehouseSuggestionTeamConfig).enabled:
        return TeamRunResult(team_id=team_id, status=TeamRunStatus.DISABLED)
    reads = read_team_reads(team_id, ReadWindow.ending(today, rules), rules, rollup_days)
    eligible = is_eligible(reads, rules.eligibility)
    status = TeamRunStatus.PROCESSED if eligible else TeamRunStatus.NOT_ELIGIBLE
    if not eligible and not _has_suggestions_to_maintain(team_id):
        with transaction.atomic():
            _record_run(_locked_config(team_id), reads, eligible=False, now=now)
        return TeamRunResult(team_id=team_id, status=status)
    context = build_context(team, reads, run_id=run_id, rules=rules, now=now)
    drafts = _evaluate_and_report(context) if eligible else []
    with transaction.atomic():
        config = _locked_config(team_id)
        _record_run(config, reads, eligible=eligible, now=now)
        lifecycle = apply_run(context, team, drafts, now, surface=eligible and config.paused_reason is None)
    return TeamRunResult(team_id=team_id, status=status, drafts=len(drafts), lifecycle=lifecycle)


def explain_team(
    team_id: int, *, today: date, rules: Rules = RULES
) -> tuple[CandidateContext, dict[WarehouseSuggestionKind, CandidateResult]]:
    team = Team.objects.get(id=team_id)
    window = ReadWindow.ending(today, rules)
    reads = read_team_reads(team_id, window, rules, read_rollup_days(window))
    context = build_context(team, reads, run_id="explain", rules=rules, now=timezone.now())
    return context, evaluate_candidates(context)


def _evaluate_and_report(context: CandidateContext) -> list[SuggestionDraft]:
    results = evaluate_candidates(context)
    for kind, result in results.items():
        report_candidates(kind, len(result.drafts))
    return [draft for result in results.values() for draft in result.drafts]


def is_eligible(reads: TeamReads, rules: EligibilityRules) -> bool:
    return reads.view_reads >= rules.min_view_reads or bool(reads.refreshes)


def build_context(team: Team, reads: TeamReads, *, run_id: str, rules: Rules, now: datetime) -> CandidateContext:
    return CandidateContext(
        team_id=team.pk,
        reads=reads,
        inventory=load_inventory(team),
        rules=rules,
        run_id=run_id,
        recent_accepts=_recent_flip_accepts(team.pk, rules, now),
    )


def _recent_flip_accepts(team_id: int, rules: Rules, now: datetime) -> dict[WarehouseSuggestionKind, frozenset[UUID]]:
    since = now - timedelta(days=rules.lifecycle.flip_cooldown_days)
    accepted = (
        WarehouseSuggestion.objects.for_team(team_id)
        .filter(status=WarehouseSuggestionStatus.ACCEPTED, kind__in=FLIP_KINDS, reviewed_at__gte=since)
        .values_list("kind", "subject_id")
    )
    subject_ids: defaultdict[WarehouseSuggestionKind, set[UUID]] = defaultdict(set)
    for kind, subject_id in accepted:
        subject_ids[WarehouseSuggestionKind(kind)].add(subject_id)
    return {kind: frozenset(ids) for kind, ids in subject_ids.items()}


def team_ids_with_suggestions_to_maintain() -> set[int]:
    return set(
        WarehouseSuggestion.objects.unscoped()
        .filter(status__in=MAINTAINED_STATUSES)
        .values_list("team_id", flat=True)
        .distinct()
    )


def _has_suggestions_to_maintain(team_id: int) -> bool:
    return WarehouseSuggestion.objects.for_team(team_id).filter(status__in=MAINTAINED_STATUSES).exists()


def _locked_config(team_id: int) -> WarehouseSuggestionTeamConfig:
    return WarehouseSuggestionTeamConfig.objects.select_for_update().get(team_id=team_id)


def _record_run(config: WarehouseSuggestionTeamConfig, reads: TeamReads, *, eligible: bool, now: datetime) -> None:
    config.eligible = eligible
    config.days_with_data = reads.days_with_data
    config.last_run_at = now
    config.save(update_fields=["eligible", "days_with_data", "last_run_at"])
