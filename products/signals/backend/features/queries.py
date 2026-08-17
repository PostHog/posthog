"""Features tab membership and lifecycle queries."""

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import FeatureLifecycle, FeatureStage


def fetch_feature_lifecycles(team_id: int) -> dict[str, FeatureLifecycle]:
    """Return each feature report's latest explicit lifecycle."""
    from products.signals.backend.models import SignalReportArtefact  # noqa: PLC0415 — avoid model import cycle

    lifecycles: dict[str, FeatureLifecycle] = {}
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        )
        .order_by("report_id", "-created_at")
        .distinct("report_id")
    )
    for report_id, content in rows.values_list("report_id", "content"):
        key = str(report_id)
        if key in lifecycles:
            continue
        try:
            lifecycles[key] = FeatureLifecycle.model_validate_json(content)
        except ValidationError:
            continue
    return lifecycles


def latest_feature_lifecycle(*, team_id: int, report_id: str) -> FeatureLifecycle | None:
    from products.signals.backend.models import SignalReportArtefact  # noqa: PLC0415 — avoid model import cycle

    content = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.FEATURE_LIFECYCLE,
        )
        .order_by("-created_at")
        .values_list("content", flat=True)
        .first()
    )
    if content is None:
        return None
    try:
        return FeatureLifecycle.model_validate_json(content)
    except ValidationError:
        return None


def fetch_feature_report_ids(team_id: int) -> list[str]:
    """Return explicit features plus legacy features identified by their planning task marker."""
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
    explicit_ids = set(fetch_feature_lifecycles(team_id))
    legacy_ids = {str(report_id) for report_id in report_ids}
    ordered = (
        SignalReport.objects.filter(team_id=team_id, id__in=explicit_ids | legacy_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .order_by("-created_at")
        .values_list("id", flat=True)
    )
    return [str(report_id) for report_id in ordered]


def fetch_feature_stages(team_id: int, report_ids: list[str]) -> dict[str, FeatureStage]:
    """Return explicit stages, falling back to legacy planning completion markers."""
    from products.signals.backend.models import SignalReportArtefact  # noqa: PLC0415 — avoid model import cycle

    lifecycles = fetch_feature_lifecycles(team_id)
    stages = {report_id: lifecycle.feature_stage for report_id, lifecycle in lifecycles.items()}
    legacy_ids = [report_id for report_id in report_ids if report_id not in stages]
    if not legacy_ids:
        return stages
    completed_ids = {
        str(report_id)
        for report_id in SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=legacy_ids,
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
        ).values_list("report_id", flat=True)
    }
    for report_id in legacy_ids:
        stages[report_id] = FeatureStage.MANAGED if report_id in completed_ids else FeatureStage.PLANNING
    return stages
