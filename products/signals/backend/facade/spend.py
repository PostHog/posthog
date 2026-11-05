from typing import TYPE_CHECKING

from products.signals.backend.spend import (
    complete_task_spend as complete_task_spend,
    register_report_task_spend as register_report_task_spend,
)
from products.signals.backend.spend_reporting import SpendReporting

if TYPE_CHECKING:
    from posthog.models import Team

    from products.signals.backend.spend_reporting import SourceSpend, SpendOverview


def scout_spend_overview(*, team: "Team") -> "SpendOverview":
    return SpendReporting(team).scouts()


def source_spend_overview(*, team: "Team") -> list["SourceSpend"]:
    return SpendReporting(team).sources()
