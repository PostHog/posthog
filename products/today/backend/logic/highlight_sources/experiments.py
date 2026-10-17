import re
from datetime import datetime, timedelta

from django.utils import timezone

from products.experiments.backend.facade.api import (
    count_enrolled_people,
    list_ended_experiments_without_conclusion,
    list_running_experiments,
)
from products.experiments.backend.facade.contracts import EndedExperiment, RunningExperiment

from ...facade.enums import HighlightLabel
from ..highlight_rules import short, users
from ..highlight_types import Candidate, Context, Found, Source

ENDED = "Experiment ‘{experiment}’ ended {when}"
ENDED_DETAIL = "Read the results and decide whether to release the change"
FEW_USERS = "Experiment ‘{experiment}’ reached {enrolled} in the last 14 days"
NO_USERS = "Experiment ‘{experiment}’ reached no users in the last 14 days"
FEW_USERS_DETAIL = "Stop it or increase the rollout"
ENDED_WINDOW_DAYS = 7
LONG_RUNNING_DAYS = 60
JUST_CROSSED_DAYS = 67
MIN_PEOPLE = 100


def find(context: Context) -> Found:
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
    return Found(
        items=(
            *(_ended(context, experiment) for experiment in ended),
            *(_few_users(experiment, people) for experiment, people in counted if people < MIN_PEOPLE),
        )
    )


def _days_since(context: Context, moment: datetime) -> int:
    return (context.today - timezone.localtime(moment, context.team.timezone_info).date()).days


def _when(days: int) -> str:
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _name(name: str, limit: int) -> str:
    return short(re.sub(r"(?i)\s+experiment$", "", name) or name, limit)


def _ended(context: Context, experiment: EndedExperiment) -> Candidate:
    return Candidate(
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


def _few_users(experiment: RunningExperiment, enrolled: int) -> Candidate:
    return Candidate(
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


SOURCE = Source(name="experiments", find=find, scopes=("experiment:read",))
