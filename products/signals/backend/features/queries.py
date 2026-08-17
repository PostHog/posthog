"""Features tab membership queries.

A feature is identified by the planning `task_run` artefact recorded at creation. Feature reports
stay outside the signal grouping pipeline; their owner scouts link related reports explicitly.
"""


def fetch_feature_report_ids(team_id: int) -> list[str]:
    """Return feature report ids newest first from their planning task markers.

    Every feature records a `signals`/`planning` task run at creation. That pair is the durable
    membership marker and is written only by this feature flow.
    """
    from products.signals.backend.models import SignalReport, SignalReportArtefact  # noqa: PLC0415 — avoid cycle

    report_ids = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.TASK_RUN,
            content__contains='"product":"signals"',
        )
        .filter(content__contains='"type":"planning"')
        .values_list("report_id", flat=True)
        .distinct()
    )
    ordered = (
        SignalReport.objects.filter(team_id=team_id, id__in=list(report_ids))
        .exclude(status=SignalReport.Status.DELETED)
        .order_by("-created_at")
        .values_list("id", flat=True)
    )
    return [str(report_id) for report_id in ordered]
