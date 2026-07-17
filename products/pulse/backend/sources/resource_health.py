from collections.abc import Callable
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.schema_enums import AlertState

from products.alerts.backend.models import AlertConfiguration
from products.exports.backend.models.subscription import SubscriptionDelivery
from products.product_analytics.backend.models.insight_caching_state import InsightCachingState
from products.pulse.backend.config import MAX_ITEMS_PER_DETECTOR, STUCK_REFRESH_ATTEMPTS
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind
from products.pulse.backend.urls import insight_url, subscription_url

logger = structlog.get_logger(__name__)


class ResourceHealthSource:
    """Broken PostHog resources the team should fix, surfaced as health items → "fix" opportunities."""

    name = "resource_health"

    def gather(self, team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]:
        detectors: list[Callable[[Team, int], list[SourceItem]]] = [
            self._errored_alerts,
            self._failed_subscription_deliveries,
            self._stuck_insight_refreshes,
        ]
        items: list[SourceItem] = []
        for detector in detectors:
            try:
                items.extend(detector(team, lookback_days))
            except Exception as exc:
                # One broken detector must not kill the brief; the others still report. Capture to
                # error tracking too (structured logs alone are easy to miss), matching the sibling
                # per-item isolation in the movement scoring strategy.
                logger.exception("pulse_resource_health_detector_failed", team_id=team.id, detector=detector.__name__)
                capture_exception(exc, {"team_id": team.id, "detector": detector.__name__, "product": "pulse"})
        return items

    def _health_item(
        self,
        *,
        title: str,
        description: str,
        ref_type: EvidenceType,
        ref: str,
        label: str,
        url: str,
        metrics: dict[str, float | int | str] | None = None,
    ) -> SourceItem:
        return SourceItem(
            source=self.name,
            kind=SourceItemKind.HEALTH,
            title=title,
            description=description,
            metrics=metrics or {},
            evidence=[EvidenceRef(type=ref_type, ref=ref, label=label, url=url)],
            fingerprint_hint=f"{ref_type}:{ref}",
        )

    def _errored_alerts(self, team: Team, lookback_days: int) -> list[SourceItem]:
        # Deliberately current-state, not period-bounded: an alert that started erroring before
        # the period is still broken now. Dismissal suppression is the off-switch.
        alerts = (
            AlertConfiguration.objects.filter(team=team, enabled=True, state=AlertState.ERRORED, insight__deleted=False)
            .select_related("insight")
            .order_by("-created_at")[:MAX_ITEMS_PER_DETECTOR]
        )
        items: list[SourceItem] = []
        for alert in alerts:
            label = alert.name or alert.insight.name or alert.insight.derived_name or str(alert.id)
            metrics: dict[str, float | int | str] = {}
            if alert.last_checked_at:
                metrics["last_checked_at"] = alert.last_checked_at.isoformat()
            items.append(
                self._health_item(
                    title=f"Alert '{label}' is failing to run",
                    description=(
                        f"The alert '{label}' is in an errored state — its checks are not completing, "
                        "so it cannot notify anyone until it is fixed."
                    ),
                    ref_type=EvidenceType.ALERT,
                    ref=str(alert.id),
                    label=label,
                    # Alerts are managed from the insight they watch.
                    url=insight_url(team.id, alert.insight.short_id),
                    metrics=metrics,
                )
            )
        return items

    def _failed_subscription_deliveries(self, team: Team, lookback_days: int) -> list[SourceItem]:
        since = timezone.now() - timedelta(days=lookback_days)
        rows = (
            SubscriptionDelivery.objects.filter(
                team=team,
                status=SubscriptionDelivery.Status.FAILED,
                created_at__gte=since,
                subscription__deleted=False,
            )
            .values(
                "subscription_id",
                "subscription__title",
                "subscription__prompt",
                "subscription__insight__short_id",
                "subscription__dashboard_id",
            )
            .annotate(failed_deliveries=Count("id"), last_failed_at=Max("created_at"))
            .order_by("-failed_deliveries")[:MAX_ITEMS_PER_DETECTOR]
        )
        items: list[SourceItem] = []
        for row in rows:
            # Prefer the subscription's own name; fall back to a prompt snippet (AI-prompt subs need
            # not be titled) before the bare id.
            label = (
                row["subscription__title"]
                or (row["subscription__prompt"] or "").strip()[:60]
                or f"Subscription {row['subscription_id']}"
            )
            count = row["failed_deliveries"]
            # Every subscription type (insight, dashboard, AI-prompt) gets a navigable link.
            url = subscription_url(
                team.id,
                row["subscription_id"],
                insight_short_id=row["subscription__insight__short_id"],
                dashboard_id=row["subscription__dashboard_id"],
            )
            items.append(
                self._health_item(
                    title=f"Subscription '{label}' failed to deliver {count} time{'s' if count != 1 else ''}",
                    description=(
                        f"The subscription '{label}' had {count} failed "
                        f"deliver{'ies' if count != 1 else 'y'} in the last {lookback_days} days — "
                        "its recipients are not receiving their reports."
                    ),
                    ref_type=EvidenceType.SUBSCRIPTION,
                    ref=str(row["subscription_id"]),
                    label=label,
                    url=url,
                    metrics={
                        "failed_deliveries": count,
                        "last_failed_at": row["last_failed_at"].isoformat(),
                    },
                )
            )
        return items

    def _stuck_insight_refreshes(self, team: Team, lookback_days: int) -> list[SourceItem]:
        # Current-state, not period-bounded (like _errored_alerts): a stuck refresh is still stuck now.
        rows = (
            InsightCachingState.objects.filter(
                team=team, refresh_attempt__gte=STUCK_REFRESH_ATTEMPTS, insight__deleted=False
            )
            .values("insight__short_id", "insight__name", "insight__derived_name")
            # Alias must not reuse the model field name "last_refresh" (annotate redefinition).
            .annotate(refresh_attempts=Max("refresh_attempt"), last_successful_refresh=Max("last_refresh"))
            .order_by("-refresh_attempts")[:MAX_ITEMS_PER_DETECTOR]
        )
        items: list[SourceItem] = []
        for row in rows:
            short_id = row["insight__short_id"]
            label = row["insight__name"] or row["insight__derived_name"] or short_id
            metrics: dict[str, float | int | str] = {"refresh_attempts": row["refresh_attempts"]}
            if row["last_successful_refresh"]:
                metrics["last_successful_refresh"] = row["last_successful_refresh"].isoformat()
            items.append(
                self._health_item(
                    title=f"Insight '{label}' is failing to refresh",
                    description=(
                        f"The insight '{label}' has failed {row['refresh_attempts']} consecutive refresh "
                        "attempts — its results are stale and it may be silently broken."
                    ),
                    ref_type=EvidenceType.INSIGHT,
                    ref=short_id,
                    label=label,
                    url=insight_url(team.id, short_id),
                    metrics=metrics,
                )
            )
        return items
