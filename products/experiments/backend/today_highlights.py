import re
from datetime import datetime, timedelta

from django.utils import timezone

from posthog.models import Team, User

from products.experiments.backend.facade.api import (
    count_enrolled_people,
    get_stored_primary_result,
    list_ended_experiments_without_conclusion,
    list_own_running_experiments,
    list_running_experiments,
    viewable_experiment_names,
)
from products.experiments.backend.facade.contracts import EndedExperiment, RunningExperiment, StoredPrimaryResult
from products.today.backend.facade.contracts import (
    HighlightCandidate,
    HighlightContext,
    HighlightExperimentResult,
    HighlightFindings,
    HighlightMetric,
)
from products.today.backend.facade.enums import HighlightLabel, HighlightMetricReason, HighlightUnit
from products.today.backend.facade.highlight_helpers import short, users

ENDED = "Experiment ‘{experiment}’ ended {when}"
ENDED_DETAIL = "Read the results and decide whether to release the change"
FEW_USERS = "Experiment ‘{experiment}’ reached {enrolled} in the last 14 days"
NO_USERS = "Experiment ‘{experiment}’ reached no users in the last 14 days"
FEW_USERS_DETAIL = "Stop it or increase the rollout"
ENDED_WINDOW_DAYS = 7
LONG_RUNNING_DAYS = 60
JUST_CROSSED_DAYS = 67
MIN_PEOPLE = 100
NUMBER_CANDIDATES = 3
NUMBER_PREFIX = "experiment:"


def _days_since(context: HighlightContext, moment: datetime) -> int:
    return (context.today - timezone.localtime(moment, context.team.timezone_info).date()).days


def _when(days: int) -> str:
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _name(name: str, limit: int) -> str:
    return short(re.sub(r"(?i)\s+experiment$", "", name) or name, limit)


def _ended(context: HighlightContext, experiment: EndedExperiment) -> HighlightCandidate:
    return HighlightCandidate(
        key=f"experiment_ended:{experiment.id}",
        label=HighlightLabel.OPPORTUNITY,
        family="experiments",
        importance=0.6,
        relevance=1.0,
        title=ENDED.format(
            experiment=_name(experiment.name, 60), when=_when(_days_since(context, experiment.ended_at))
        ),
        detail=ENDED_DETAIL,
        url=f"/experiments/{experiment.id}",
    )


def _few_users(experiment: RunningExperiment, enrolled: int) -> HighlightCandidate:
    return HighlightCandidate(
        key=f"experiment_stale:{experiment.id}",
        label=HighlightLabel.RISK,
        family="experiments",
        importance=0.3,
        relevance=1.0,
        title=(FEW_USERS if enrolled else NO_USERS).format(
            experiment=_name(experiment.name, 50), enrolled=users(enrolled)
        ),
        detail=FEW_USERS_DETAIL,
        url=f"/experiments/{experiment.id}",
    )


def _number(experiment: RunningExperiment, result: StoredPrimaryResult) -> HighlightMetric | None:
    direction = -1 if result.goal == "decrease" else 1
    ranked = sorted(
        (variant for variant in result.variants if variant.change is not None),
        key=lambda variant: (variant.change or 0) * direction,
        reverse=True,
    )
    shown = next((variant for variant in ranked if variant.significant), ranked[0] if ranked else None)
    if shown is None or shown.change is None:
        return None
    return HighlightMetric(
        key=f"{NUMBER_PREFIX}{experiment.id}",
        name=_name(experiment.name, 60),
        value=shown.change * 100,
        unit=HighlightUnit.NUMBER,
        change_pct=None,
        series=[],
        url=f"/experiments/{experiment.id}",
        reason=HighlightMetricReason.EXPERIMENT,
        experiment=HighlightExperimentResult(
            metric_name=result.metric_name,
            variant=shown.key,
            control=result.baseline.key,
            variants=len(result.variants),
            significant=bool(shown.significant),
            favorable=shown.change * direction > 0,
            exposures=result.baseline.number_of_samples + sum(variant.number_of_samples for variant in result.variants),
        ),
    )


def find_experiment_number(context: HighlightContext) -> HighlightFindings:
    running = list_own_running_experiments(team_id=context.team.id, user_id=context.user.id, limit=NUMBER_CANDIDATES)
    for experiment in running:
        if f"{NUMBER_PREFIX}{experiment.id}" in context.hidden:
            continue
        result = get_stored_primary_result(team_id=context.team.id, experiment_id=experiment.id)
        number = _number(experiment, result) if result is not None else None
        if number is not None:
            return HighlightFindings(pulse=(number,))
    return HighlightFindings()


def name_experiment_numbers(team: Team, user: User, keys: list[str]) -> dict[str, str]:
    ids = {
        int(id) for key in keys if key.startswith(NUMBER_PREFIX) and (id := key.removeprefix(NUMBER_PREFIX)).isdigit()
    }
    names = viewable_experiment_names(team=team, user=user, experiment_ids=ids) if ids else {}
    return {f"{NUMBER_PREFIX}{id}": _name(name, 60) for id, name in names.items()}


def find_experiment_highlights(context: HighlightContext) -> HighlightFindings:
    now = timezone.now()
    ended = list_ended_experiments_without_conclusion(
        team_id=context.team.id, user_id=context.user.id, since=now - timedelta(days=ENDED_WINDOW_DAYS), limit=20
    )
    running = list_running_experiments(
        team_id=context.team.id,
        user_id=context.user.id,
        started_after=None if context.today.weekday() == 0 else now - timedelta(days=JUST_CROSSED_DAYS),
        started_before=now - timedelta(days=LONG_RUNNING_DAYS),
        limit=100,
    )
    enrolled = context.guard(
        "experiments_enrolled",
        lambda: count_enrolled_people(
            team=context.team, user=context.user, flag_keys=[experiment.flag_key for experiment in running]
        ),
        None,
    )
    counted = [] if enrolled is None else [(experiment, enrolled.get(experiment.flag_key, 0)) for experiment in running]
    return HighlightFindings(
        items=(
            *(_ended(context, experiment) for experiment in ended),
            *(_few_users(experiment, people) for experiment, people in counted if people < MIN_PEOPLE),
        )
    )
