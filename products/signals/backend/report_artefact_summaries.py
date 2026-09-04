"""Per-page artefact summaries for the reports list.

The reports viewset renders two artefact-derived values on every row: how many artefacts a
report has, and the space it is assigned to. Annotated on the queryset, each one is a
correlated subquery, so each costs a walk of `signals_signalreportartefact` per row the query
returns. A list already knows the page it returns, so it asks for the whole page at once
instead. A report with no artefacts, or no live space, is absent from its map.
"""

from collections.abc import Sequence
from uuid import UUID

from django.db.models import Count

from products.signals.backend.models import SignalReportArtefact


def artefact_count_by_report(report_ids: Sequence[str | UUID]) -> dict[str, int]:
    """Artefact count per report, in one grouped query. Absent means zero."""
    rows = SignalReportArtefact.objects.filter(report_id__in=report_ids).values("report_id").annotate(count=Count("*"))
    return {str(row["report_id"]): row["count"] for row in rows}


def live_channel_id_by_report(report_ids: Sequence[str | UUID]) -> dict[str, UUID]:
    """The space each report is assigned to, in one `DISTINCT ON` pass.

    The latest channel_assignment artefact wins. A report assigned to a since-deleted space
    reads as unassigned, rather than falling back to the space it was assigned to before that.
    """
    rows = (
        SignalReportArtefact.objects.filter(
            report_id__in=report_ids,
            type=SignalReportArtefact.ArtefactType.CHANNEL_ASSIGNMENT,
        )
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values_list("report_id", "channel_id", "channel__deleted")
    )
    return {str(report_id): channel_id for report_id, channel_id, deleted in rows if channel_id and deleted is False}
