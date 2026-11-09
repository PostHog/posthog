"""Resolve the `recommended` inbox sort to an arm, and give each row a merge key.

A multivariate flag keyed by the requesting user picks the arm. An arm is a ranker and a pill setting:

| Variant        | Ranker   | Pill |
|----------------|----------|------|
| `control`      | priority | no   |
| `pills`        | priority | yes  |
| `action_pills` | action   | yes  |

An unknown variant, or a flag that is off or fails to evaluate, gives `control`.

A head ranker sorts by the served score of its outcome, highest first, then in priority order. Unscored and stale
reports come after every scored report, in priority order. The merge key follows the same order, so a client can merge
rows from different state requests: `1 - score` for a scored report, `2 + priority rank` for an unscored report, and
the priority rank alone for the priority ranker.
"""

from typing import Literal, get_args

from django.db.models import Case, CharField, F, FloatField, Func, JSONField, OuterRef, Subquery, Value, When
from django.db.models.functions import Cast

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.signals.backend.models import AutonomyPriority, SignalReportArtefact
from products.signals.backend.ranking.public_outcomes import PublicOutcomeName
from products.signals.backend.ranking.staleness import annotate_stale_score

logger = structlog.get_logger(__name__)

RECOMMENDED_INBOX_SORT_FLAG = "signals-inbox-ranking-pills"

HeadRanker = PublicOutcomeName
InboxRanker = Literal["priority", HeadRanker]

HEAD_RANKERS: tuple[HeadRanker, ...] = get_args(HeadRanker)

PRIORITY_ORDERING = "priority,status,-updated_at"
RANKER_ORDERINGS: dict[InboxRanker, str] = {
    "priority": PRIORITY_ORDERING,
    **{head: f"-ranking_{head},{PRIORITY_ORDERING}" for head in HEAD_RANKERS},
}

_PRIORITY_SLOTS = len(AutonomyPriority.values) + 1
_UNSCORED_MERGE_KEY_BASE = 2.0


@frozen
class RecommendedArm:
    ranker: InboxRanker
    ranking_pill: bool


CONTROL_ARM = RecommendedArm(ranker="priority", ranking_pill=False)
RECOMMENDED_ARMS: dict[str, RecommendedArm] = {
    "control": CONTROL_ARM,
    "pills": RecommendedArm(ranker="priority", ranking_pill=True),
    "action_pills": RecommendedArm(ranker="action", ranking_pill=True),
}


def resolve_recommended_arm(team: Team, user: User, *, send_feature_flag_events: bool = True) -> RecommendedArm:
    """`send_feature_flag_events=False` reads the variant without an exposure, for a caller that does not show the inbox."""
    if not user.distinct_id:
        return CONTROL_ARM
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
        return CONTROL_ARM
    return RECOMMENDED_ARMS.get(variant, CONTROL_ARM) if isinstance(variant, str) else CONTROL_ARM


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


def _clamped_priority_rank(priority_rank: int | None) -> int:
    return _PRIORITY_SLOTS - 1 if priority_rank is None else min(max(priority_rank, 0), _PRIORITY_SLOTS - 1)


def inbox_merge_key(ranker: InboxRanker, score: float | None, priority_rank: int | None) -> float:
    """Lower keys rank first. For a head ranker, a report without a score sorts after every scored report."""
    priority = _clamped_priority_rank(priority_rank)
    if ranker == "priority":
        return float(priority)
    if score is None:
        return _UNSCORED_MERGE_KEY_BASE + priority
    return 1.0 - min(max(score, 0.0), 1.0)
