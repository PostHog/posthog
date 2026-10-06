"""When a served ranking score no longer describes the report's text.

A score is stale when the report's title or summary was edited after the vector the score read.
Only the two edit paths (the report PATCH and the scout `edit_report` tool) write the edit
artefacts, so the pipeline's own rewrites never mark a score stale.

The time a score is compared against is the landing time of the vector it read, not `scored_at`.
`scored_at` is the start of the sweep pass, and a team's vectors are read later in the pass. An
edit that is indexed in that gap gives a score on the new text with a `scored_at` before the edit.
The vector lands after the commit of the edit that produced it, so a vector newer than the edit
holds the edited text. A score with no vector time falls back to `scored_at`.

The serializer and the model sort both use this rule. Keep `is_stale_score` and
`annotate_stale_score` in step.
"""

from datetime import datetime

from django.db.models import Case, CharField, DateTimeField, Exists, F, Func, JSONField, OuterRef, QuerySet, Value, When
from django.db.models.functions import Cast, Coalesce

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReportArtefact

EDIT_ARTEFACT_TYPES: tuple[str, ...] = (
    SignalReportArtefact.ArtefactType.TITLE_CHANGE,
    SignalReportArtefact.ArtefactType.SUMMARY_CHANGE,
)

# The ISO 8601 form pydantic writes for an aware datetime. A naive value has no fixed instant, so it
# is not read. One cast error in the sort subquery would fail the whole list, so the value is
# parsed by a silent jsonpath `datetime()`, which gives NULL for an impossible date or time.
# That parser does not accept a `Z` offset, so `Z` becomes `+00:00` first.
_ISO_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
_SAFE_TIMESTAMP_TEMPLATE = (
    "(jsonb_path_query_first(to_jsonb(regexp_replace(%(expressions)s, 'Z$', '+00:00')), "
    "'$.datetime()', '{}', true) #>> '{}')"
)


def score_read_at(score: RankingScore) -> datetime:
    """The time of the text the score describes."""
    return score.embedding_inserted_at or score.scored_at


def is_stale_score(score: RankingScore, latest_edit_at: datetime | None) -> bool:
    read_at = score_read_at(score)
    # The sort does not read a naive time, so it is not stale here either.
    if latest_edit_at is None or read_at.tzinfo is None:
        return False
    return latest_edit_at > read_at


def annotate_stale_score(scores: QuerySet[SignalReportArtefact]) -> QuerySet[SignalReportArtefact]:
    """Annotate `ranking_score` artefacts with `_score_is_stale`: true when an edit artefact is newer than the score.

    A row whose content is not a JSON object, or whose time does not parse, reads as not stale.
    """
    content = Cast(F("content"), output_field=JSONField())
    read_at_text = Coalesce(
        Func(content, Value("embedding_inserted_at"), function="jsonb_extract_path_text", output_field=CharField()),
        Func(content, Value("scored_at"), function="jsonb_extract_path_text", output_field=CharField()),
        output_field=CharField(),
    )
    return (
        scores.annotate(
            _score_read_at_text=Case(
                When(content__startswith="{", then=read_at_text),
                default=Value(None),
                output_field=CharField(),
            )
        )
        .annotate(
            _score_read_at=Case(
                When(
                    _score_read_at_text__regex=_ISO_TIMESTAMP_PATTERN,
                    then=Cast(
                        Func(F("_score_read_at_text"), template=_SAFE_TIMESTAMP_TEMPLATE, output_field=CharField()),
                        output_field=DateTimeField(),
                    ),
                ),
                default=Value(None),
                output_field=DateTimeField(),
            )
        )
        .annotate(
            _score_is_stale=Exists(
                SignalReportArtefact.objects.filter(
                    report_id=OuterRef("report_id"),
                    type__in=EDIT_ARTEFACT_TYPES,
                    created_at__gt=OuterRef("_score_read_at"),
                )
            )
        )
    )
