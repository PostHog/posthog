from collections.abc import Callable
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

import structlog

from posthog.models.team import Team
from posthog.schema_enums import AlertState

from products.alerts.backend.models import AlertConfiguration
from products.exports.backend.models.subscription import SubscriptionDelivery
from products.product_analytics.backend.models.insight_caching_state import InsightCachingState
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem

logger = structlog.get_logger(__name__)

MAX_ITEMS_PER_DETECTOR = 10
# Mirrors posthog.caching.insight_cache.MAX_ATTEMPTS (not imported: that module drags the
# celery task graph onto this import path). At this count the cache updater has given up.
STUCK_REFRESH_ATTEMPTS = 3


class ResourceHealthSource:
    name = "resource_health"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        detectors: list[Callable[[Team, int], list[SourceItem]]] = [
            self._errored_alerts,
            self._failed_subscription_deliveries,
            self._stuck_insight_refreshes,
        ]
        items: list[SourceItem] = []
        for detector in detectors:
            try:
                items.extend(detector(team, period_days))
            except Exception:
                # One broken detector must not kill the brief; the others still report.
                logger.exception("pulse_resource_health_detector_failed", team_id=team.id, detector=detector.__name__)
        return items

    def _errored_alerts(self, team: Team, period_days: int) -> list[SourceItem]:
        alerts = AlertConfiguration.objects.filter(team=team, enabled=True, state=AlertState.ERRORED).select_related(
            "insight"
        )[:MAX_ITEMS_PER_DETECTOR]
        items: list[SourceItem] = []
        for alert in alerts:
            label = alert.name or alert.insight.name or alert.insight.derived_name or str(alert.id)
            numbers: dict[str, float | int | str] = {}
            if alert.last_checked_at:
                numbers["last_checked_at"] = alert.last_checked_at.isoformat()
            items.append(
                SourceItem(
                    source=self.name,
                    kind="health",
                    title=f"Alert '{label}' is failing to run",
                    description=(
                        f"The alert '{label}' is in an errored state — its checks are not completing, "
                        "so it cannot notify anyone until it is fixed."
                    ),
                    numbers=numbers,
                    evidence=[EvidenceRef(type="alert", ref=str(alert.id), label=label)],
                    fingerprint_hint=f"health:alert:{alert.id}",
                )
            )
        return items

    def _failed_subscription_deliveries(self, team: Team, period_days: int) -> list[SourceItem]:
        since = timezone.now() - timedelta(days=period_days)
        rows = (
            SubscriptionDelivery.objects.filter(
                team=team,
                status=SubscriptionDelivery.Status.FAILED,
                created_at__gte=since,
                subscription__deleted=False,
            )
            .values("subscription_id", "subscription__title")
            .annotate(failed_deliveries=Count("id"), last_failed_at=Max("created_at"))
            .order_by("-failed_deliveries")[:MAX_ITEMS_PER_DETECTOR]
        )
        items: list[SourceItem] = []
        for row in rows:
            label = row["subscription__title"] or f"Subscription {row['subscription_id']}"
            count = row["failed_deliveries"]
            items.append(
                SourceItem(
                    source=self.name,
                    kind="health",
                    title=f"Subscription '{label}' failed to deliver {count} time{'s' if count != 1 else ''}",
                    description=(
                        f"The subscription '{label}' had {count} failed "
                        f"deliver{'ies' if count != 1 else 'y'} in the last {period_days} days — "
                        "its recipients are not receiving their reports."
                    ),
                    numbers={
                        "failed_deliveries": count,
                        "since": since.isoformat(),
                        "last_failed_at": row["last_failed_at"].isoformat(),
                    },
                    evidence=[EvidenceRef(type="subscription", ref=str(row["subscription_id"]), label=label)],
                    fingerprint_hint=f"health:subscription:{row['subscription_id']}",
                )
            )
        return items

    def _stuck_insight_refreshes(self, team: Team, period_days: int) -> list[SourceItem]:
        rows = (
            InsightCachingState.objects.filter(
                team=team, refresh_attempt__gte=STUCK_REFRESH_ATTEMPTS, insight__deleted=False
            )
            .values("insight__short_id", "insight__name", "insight__derived_name")
            .annotate(refresh_attempts=Max("refresh_attempt"), last_refresh=Max("last_refresh"))
            .order_by("-refresh_attempts")[:MAX_ITEMS_PER_DETECTOR]
        )
        items: list[SourceItem] = []
        for row in rows:
            short_id = row["insight__short_id"]
            label = row["insight__name"] or row["insight__derived_name"] or short_id
            numbers: dict[str, float | int | str] = {"refresh_attempts": row["refresh_attempts"]}
            if row["last_refresh"]:
                numbers["last_successful_refresh"] = row["last_refresh"].isoformat()
            items.append(
                SourceItem(
                    source=self.name,
                    kind="health",
                    title=f"Insight '{label}' is failing to refresh",
                    description=(
                        f"The insight '{label}' has failed {row['refresh_attempts']} consecutive refresh "
                        "attempts — its results are stale and it may be silently broken."
                    ),
                    numbers=numbers,
                    evidence=[EvidenceRef(type="insight", ref=short_id, label=label)],
                    fingerprint_hint=f"health:insight:{short_id}",
                )
            )
        return items
