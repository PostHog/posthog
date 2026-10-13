from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.signals.backend.models import SignalReportCheck


def check_versions(checks: Iterable[SignalReportCheck]) -> dict[str, str]:
    return {str(check.id): check.updated_at.isoformat() for check in checks}


def research_can_reconcile_checks(checks: list[SignalReportCheck], snapshot: Mapping[str, str] | None) -> bool:
    if snapshot is None:
        # Old activity results cannot establish whether research saw a person's selection.
        return not any(check.actor_kind in ("user", "agent") or check.approved_at is not None for check in checks)
    return check_versions(checks) == snapshot
