from typing import TYPE_CHECKING, Any

from django.db.models import Q

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from products.replay_vision.backend.models import ReplayObservation


def apply_observation_predicate(
    queryset: "QuerySet[ReplayObservation]", selection: dict[str, Any]
) -> "QuerySet[ReplayObservation]":
    """Narrow an observation queryset to the alert's targeting predicate ("run this on…").

    Filters on the persisted `scanner_result["model_output"]` JSON: monitor verdicts, classifier tags
    (fixed or freeform, any-of), and scorer score bounds. Empty or absent keys are ignored, so a
    default `selection` matches everything. Verdict/score filters implicitly exclude observations of
    other scanner types (the JSON key is absent there), which is what targeting means.
    """
    verdicts = selection.get("verdict") or []
    if isinstance(verdicts, str):  # tolerate a legacy single-string row
        verdicts = [verdicts]
    if verdicts:
        queryset = queryset.filter(scanner_result__model_output__verdict__in=verdicts)

    tags = selection.get("tags") or []
    if tags:
        # `__contains` on a JSONB array uses `@>`: matches when the stored array contains the element.
        tag_q = Q()
        for tag in tags:
            tag_q |= Q(scanner_result__model_output__tags__contains=[tag])
            tag_q |= Q(scanner_result__model_output__tags_freeform__contains=[tag])
        queryset = queryset.filter(tag_q)

    # jsonb comparison is numeric for JSON numbers, so these bounds work for int and float scores.
    # bool is rejected explicitly (it's an int subclass but a nonsensical bound).
    min_score = selection.get("min_score")
    if isinstance(min_score, int | float) and not isinstance(min_score, bool):
        queryset = queryset.filter(scanner_result__model_output__score__gte=min_score)
    max_score = selection.get("max_score")
    if isinstance(max_score, int | float) and not isinstance(max_score, bool):
        queryset = queryset.filter(scanner_result__model_output__score__lte=max_score)

    return queryset
