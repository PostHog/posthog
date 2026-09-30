"""Insight alerts the person created or follows that are firing now."""

from products.alerts.backend.facade import api as alerts

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import Candidate, SourceContext, app_url
from .base import Source


class AlertsSource(Source):
    name = "alerts"

    def collect(self, ctx: SourceContext) -> list[Candidate]:
        return [
            Candidate(
                key=f"alert:{alert.alert_id}",
                group=ItemGroup.DASHBOARD,
                source=ItemSource.ALERTS,
                reason=ItemReason.ALERT_FIRING,
                title=alert.name,
                url=app_url(ctx.team.id, f"insights/{alert.insight_short_id}"),
                # Firing alerts rank before dashboard and insight changes.
                sort_key=(0, -(alert.last_checked_at.timestamp() if alert.last_checked_at else 0)),
                facts={"alert": alert.name, "insight": alert.insight_name, "state": "firing"},
            )
            for alert in alerts.firing_alerts_for_user(team_id=ctx.team.id, user_id=ctx.user.id)
        ]
