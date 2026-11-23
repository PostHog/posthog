"""The order of the ranked inbox sorts, and the merge key of each row.

`sort=recommended` and `sort=personal` put the stored personal list first, then every other report in priority
order. Without a stored list, they give the priority order. The merge key of a row outside the list is its priority
rank, so a client can merge rows from different state requests.
"""

from typing import Literal

from django.db.models import Case, CharField, F, FloatField, Func, JSONField, OuterRef, Subquery, Value, When
from django.db.models.functions import Cast

from products.signals.backend.models import AutonomyPriority, SignalReportArtefact

PRIORITY_ORDERING = "priority,status,-updated_at"

_PRIORITY_SLOTS = len(AutonomyPriority.values) + 1


def latest_ranking_value(head: str, key: Literal["scores", "lifts"]) -> Subquery:
    # The served model's value for one head from the latest ranking_score artefact, as
    # `results -> <served_key> -> <key> -> <head>`. A value that is not a JSON number reads as NULL,
    # so one bad row cannot fail the list. The guard is in the CASE, not the filter: the latest
    # artefact decides, as it does for the `ranking` field, so a bad latest row makes the report
    # unscored rather than older-scored.
    content = Cast(F("content"), output_field=JSONField())
    served_key = Func(content, Value("served_key"), function="jsonb_extract_path_text", output_field=CharField())
    return Subquery(
        SignalReportArtefact.objects.filter(
            report_id=OuterRef("id"),
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
        )
        .order_by("-created_at")
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
                When(_score_type="number", then=Cast(F("_score"), output_field=FloatField())),
                default=Value(None),
                output_field=FloatField(),
            )
        )
        .values("_score_value")[:1],
        output_field=FloatField(),
    )


def inbox_merge_key(priority_rank: int | None) -> float:
    """Lower keys rank first. A report with no priority rank sorts last."""
    return float(_PRIORITY_SLOTS - 1 if priority_rank is None else min(max(priority_rank, 0), _PRIORITY_SLOTS - 1))
