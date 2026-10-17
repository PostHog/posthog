"""Resolve the `recommended` inbox sort to a ranker, and give each row a coarse merge key.

A multivariate flag keyed by the requesting user picks the ranker. The variants `open`, `action` and `fixed` order
by the served head of the same name first. `control`, an unknown variant, or a flag that is off or fails to evaluate
gives the priority order. The EU instance gives the priority order without evaluating the flag.

The merge key lets a client merge rows from different rankers without the raw score. It is the score
decile then the priority rank, so it never says more about the score than one decimal place. Each
head ranker sorts by the same decile, so the row order does not say more either. The database
computes the decile with `score_decile`, and `inbox_merge_key` reads that value.
"""

from typing import Literal, get_args

from django.contrib.postgres.fields import ArrayField
from django.db.models import Expression, FloatField, Func, IntegerField, Value

import structlog
import posthoganalytics

from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import get_instance_region

from products.signals.backend.models import AutonomyPriority

logger = structlog.get_logger(__name__)

RECOMMENDED_INBOX_SORT_FLAG = "signals-inbox-recommended-sort"

InboxRanker = Literal["priority", "open", "action", "fixed"]
HeadRanker = Literal["open", "action", "fixed"]

HEAD_RANKERS: tuple[HeadRanker, ...] = get_args(HeadRanker)

PRIORITY_ORDERING = "priority,status,-updated_at"
RANKER_ORDERINGS: dict[InboxRanker, str] = {
    "priority": PRIORITY_ORDERING,
    **{head: f"-ranking_{head},{PRIORITY_ORDERING}" for head in HEAD_RANKERS},
}

_DECILES = 10
_PRIORITY_SLOTS = len(AutonomyPriority.values) + 1


def resolve_recommended_ranker(team: Team, user: User) -> InboxRanker:
    if not user.distinct_id:
        return "priority"
    # EU reports have no ranking scores, so a head variant there sorts the same as `control`. Evaluating the
    # flag would still log an exposure, and those no-difference exposures would dilute the US experiment.
    if get_instance_region() == "EU":
        return "priority"
    try:
        variant = posthoganalytics.get_feature_flag(
            RECOMMENDED_INBOX_SORT_FLAG,
            # Keyed by user so the exposure joins to the user's inbox events in the experiment.
            user.distinct_id,
            # The web and desktop clients register the project group by uuid, so all clients get the same variant.
            groups={"project": str(team.uuid)},
            group_properties={"project": {"id": team.id, "uuid": str(team.uuid)}},
        )
    except Exception:
        logger.exception("signals.inbox_sort.flag_failed", team_id=team.id, user_id=user.id)
        return "priority"
    for head in HEAD_RANKERS:
        if variant == head:
            return head
    return "priority"


def score_decile(score: Expression) -> Func:
    """The score decile, 0 to 9. A score below 0 gives 0, a score of 0.9 or more gives 9, and NULL stays NULL.

    `width_bucket` reads the score once. A CASE repeats the score in each branch, so when the score is a
    correlated subquery, Postgres runs the subquery once per branch.
    """
    thresholds = Value([float(bound) for bound in range(1, _DECILES)], output_field=ArrayField(FloatField()))
    return Func(score * _DECILES, thresholds, function="width_bucket", output_field=IntegerField())


def inbox_merge_key(decile: int | None, priority_rank: int | None) -> int:
    """Lower keys rank first. A report without a score sorts after every scored report."""
    decile_rank = _DECILES if decile is None else _DECILES - 1 - decile
    priority = _PRIORITY_SLOTS - 1 if priority_rank is None else min(max(priority_rank, 0), _PRIORITY_SLOTS - 1)
    return decile_rank * _PRIORITY_SLOTS + priority
