"""Resolve the `recommended` inbox sort to a ranker, and give each row a coarse merge key.

A multivariate flag keyed by the requesting user picks the ranker. The variants `open`, `action` and `fix` order
by the served outcome of the same name first. `control`, an unknown variant, or a flag that is off or fails to evaluate
gives the priority order. The EU instance gives the priority order without evaluating the flag.

The merge key lets a client merge rows from different rankers without the raw score. It is the score
decile then the priority rank, so it never says more about the score than one decimal place. Each
head ranker sorts by the same decile, so the row order does not say more either. The database
computes the decile with `score_decile`, and `inbox_merge_key` reads that value.
"""

from typing import Literal, get_args

from django.contrib.postgres.fields import ArrayField
from django.db.models import (
    Case,
    CharField,
    F,
    FloatField,
    Func,
    IntegerField,
    JSONField,
    OuterRef,
    Subquery,
    Value,
    When,
)
from django.db.models.expressions import Combinable
from django.db.models.functions import Cast

import structlog
import posthoganalytics

from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import get_instance_region

from products.signals.backend.models import AutonomyPriority, SignalReportArtefact
from products.signals.backend.ranking.public_outcomes import PublicOutcomeName
from products.signals.backend.ranking.staleness import annotate_stale_score

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


def resolve_recommended_ranker(team: Team, user: User, *, send_feature_flag_events: bool = True) -> InboxRanker:
    """`send_feature_flag_events=False` reads the variant without an exposure, for a caller that does not show the inbox."""
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
            send_feature_flag_events=send_feature_flag_events,
        )
    except Exception:
        logger.exception("signals.inbox_sort.flag_failed", team_id=team.id, user_id=user.id)
        return "priority"
    for head in HEAD_RANKERS:
        if variant == head:
            return head
    return "priority"


def latest_ranking_value(head: str, key: Literal["scores", "lifts"]) -> Subquery:
    # The served model's value for one head from the latest ranking_score artefact, as
    # `results -> <served_key> -> <key> -> <head>`. A value that is not a JSON number reads as NULL,
    # so one bad row cannot fail the list. The guard is in the CASE, not the filter: the latest
    # artefact decides, as it does for the `ranking` field, so a bad latest row makes the report
    # unscored rather than older-scored. A stale score (the report was edited after the text it
    # scored) also reads as NULL.
    content = Cast(F("content"), output_field=JSONField())
    served_key = Func(content, Value("served_key"), function="jsonb_extract_path_text", output_field=CharField())
    return Subquery(
        annotate_stale_score(
            SignalReportArtefact.objects.filter(
                report_id=OuterRef("id"),
                type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            ).order_by("-created_at")
        )
        .annotate(
            _score=Case(
                When(
                    content__startswith="{",
                    then=Func(
                        content,
                        Value("results"),
                        served_key,
                        Value(key),
                        Value(head),
                        function="jsonb_extract_path",
                        output_field=JSONField(),
                    ),
                ),
                default=Value(None),
                output_field=JSONField(),
            ),
        )
        .annotate(_score_type=Func(F("_score"), function="jsonb_typeof", output_field=CharField()))
        .annotate(
            _score_value=Case(
                When(
                    _score_type="number",
                    _score_is_stale=False,
                    then=Cast(F("_score"), output_field=FloatField()),
                ),
                default=Value(None),
                output_field=FloatField(),
            )
        )
        .values("_score_value")[:1],
        output_field=FloatField(),
    )


def score_decile(score: Combinable) -> Func:
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
