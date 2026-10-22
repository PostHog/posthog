"""
Facade for uptime_monitoring.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from ..feature_flags import is_uptime_monitoring_enabled


def is_enabled(team_id: int) -> bool:
    return is_uptime_monitoring_enabled(team_id)
