"""Resolve the `recommended` inbox sort to a ranker, and give each row a coarse merge key.

A multivariate flag keyed by the requesting user picks the ranker. The variants `open`, `action` and `fix` order
by the served outcome of the same name first. `control`, an unknown variant, or a flag that is off or fails to evaluate
gives the priority order. The EU instance gives the priority order without evaluating the flag.

The merge key lets a client merge rows from different rankers without the raw score. It is the score
decile then the priority rank, so it never says more about the score than one decimal place. Each
head ranker sorts by the same decile, so the row order does not say more either. Keep
`score_decile` and `inbox_merge_key` in step.
"""

from typing import Literal, get_args

from django.db.models import Case, F, FloatField, Value, When
from django.db.models.functions import Floor

import structlog
import posthoganalytics

from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import get_instance_region

from products.signals.backend.models import AutonomyPriority
from products.signals.backend.ranking.public_outcomes import PublicOutcomeName

logger = structlog.get_logger(__name__)

RECOMMENDED_INBOX_SORT_FLAG = "signals-inbox-recommended-sort"

HeadRanker = PublicOutcomeName
InboxRanker = Literal["priority", HeadRanker]

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


def score_decile(field: str) -> Case:
    """The SQL form of the decile in `inbox_merge_key`. NULL stays NULL."""
    return Case(
        When(**{f"{field}__isnull": True}, then=Value(None)),
        When(**{f"{field}__lt": 0}, then=Value(0.0)),
        When(**{f"{field}__gte": (_DECILES - 1) / _DECILES}, then=Value(float(_DECILES - 1))),
        default=Floor(F(field) * _DECILES),
        output_field=FloatField(),
    )


def inbox_merge_key(score: float | None, priority_rank: int | None) -> int:
    """Lower keys rank first. A report without a score sorts after every scored report."""
    if score is None:
        decile_rank = _DECILES
    else:
        decile = min(max(int(score * _DECILES), 0), _DECILES - 1)
        decile_rank = _DECILES - 1 - decile
    priority = _PRIORITY_SLOTS - 1 if priority_rank is None else min(max(priority_rank, 0), _PRIORITY_SLOTS - 1)
    return decile_rank * _PRIORITY_SLOTS + priority
