"""Plan tab membership queries.

A plan report is identified by its Postgres planning marker — the `task_run` artefact with the
`planning` type that `service.create_plan` records at creation. Plans deliberately have no backing
signal and never touch the grouping pipeline; relatedness to other reports is the owner scout's job
(`associated_report` artefacts).
"""


def fetch_planning_marker_report_ids(team_id: int) -> list[str]:
    """Report ids carrying the plan-mode marker, newest report first — from Postgres, not ClickHouse.

    Every plan created through the plan flow records a `task_run` artefact with the `planning` type
    (see `service.create_plan`), which doubles as the durable membership marker: it exists from the
    moment of creation, so drafts are reachable before their backing `inbox`/`plan` signal is emitted
    at finish (and finished plans stay reachable even if the signal write hasn't landed). The filter
    string-matches the artefact's compact JSON — safe because plan mode is the only writer of the
    `signals`/`planning` pair.
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
