from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from products.signals.backend.artefact_schemas import CheckAuthoringStatus
from products.signals.backend.models import SignalReportArtefact

if TYPE_CHECKING:
    from products.signals.backend.models import SignalReport, SignalReportCheck


def check_authoring_failed(report: SignalReport) -> bool:
    """Use the locked report's writer so replica lag cannot hide a new authoring failure."""
    authoring = (
        SignalReportArtefact.objects.using(report._state.db or "default")
        .filter(team_id=report.team_id, report_id=report.id, type=SignalReportArtefact.ArtefactType.CHECK_AUTHORING)
        .order_by("-created_at", "-id")
        .first()
    )
    return authoring is not None and CheckAuthoringStatus.model_validate_json(authoring.content).status == "failed"


def check_versions(checks: Iterable[SignalReportCheck]) -> dict[str, str]:
    return {str(check.id): check.updated_at.isoformat() for check in checks}


def research_can_reconcile_checks(checks: list[SignalReportCheck], snapshot: Mapping[str, str] | None) -> bool:
    if snapshot is None:
        # Old activity results cannot establish whether research saw a person's selection.
        return not any(check.actor_kind in ("user", "agent") or check.approved_at is not None for check in checks)
    return check_versions(checks) == snapshot
