from datetime import datetime
from decimal import Decimal

from django.db.models import Q

from posthog.dataclasses import frozen

from ..models import SignalScoutGoal, SignalScoutGoalIdea, SignalSpend

IMPLEMENTATION_KINDS = (
    SignalSpend.Kind.REVIEWER_TRIGGERED_IMPLEMENTATION,
    SignalSpend.Kind.SCOUT_TRIGGERED_IMPLEMENTATION,
)


@frozen
class SpendPoint:
    at: datetime
    spent_cents: int
    kind: str
    report_id: str | None


@frozen
class GoalSpend:
    spent_cents: int
    scout_cents: int
    scout_runs: int
    ideas_cents: int
    tracking_cents: int
    by_report: dict[str, int]
    points: list[SpendPoint]


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal(1)))


def goal_spend(goal: SignalScoutGoal) -> GoalSpend:
    kinds = {
        str(report_id): kind
        for report_id, kind in SignalScoutGoalIdea.objects.for_team(goal.team_id)
        .filter(goal=goal)
        .values_list("report_id", "kind")
    }
    rows = (
        SignalSpend.objects.for_team(goal.team_id)
        .filter(
            Q(kind=SignalSpend.Kind.SCOUT_RUN, scout_run__scout_config_id=goal.pk)
            | Q(kind__in=IMPLEMENTATION_KINDS, report_id__in=list(kinds))
        )
        .order_by("created_at")
        .values_list("kind", "spend", "scout_run_id", "report_id", "created_at")
    )
    scout = Decimal(0)
    ideas = Decimal(0)
    tracking = Decimal(0)
    runs: set[str] = set()
    by_report: dict[str, Decimal] = {}
    points: list[SpendPoint] = []
    for kind, amount, scout_run_id, report_id, created_at in rows:
        amount = amount or Decimal(0)
        if kind == SignalSpend.Kind.SCOUT_RUN:
            scout += amount
            runs.add(str(scout_run_id))
        elif kinds.get(str(report_id)) == SignalScoutGoalIdea.Kind.TRACKING:
            tracking += amount
        else:
            ideas += amount
        if report_id is not None:
            by_report[str(report_id)] = by_report.get(str(report_id), Decimal(0)) + amount
        points.append(
            SpendPoint(
                at=created_at,
                spent_cents=_cents(amount),
                kind=kind or "",
                report_id=str(report_id) if report_id else None,
            )
        )
    return GoalSpend(
        spent_cents=_cents(scout + ideas + tracking),
        scout_cents=_cents(scout),
        scout_runs=len(runs),
        ideas_cents=_cents(ideas),
        tracking_cents=_cents(tracking),
        by_report={report_id: _cents(amount) for report_id, amount in by_report.items()},
        points=points,
    )
