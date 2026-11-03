from datetime import UTC, date, datetime, time, timedelta
from itertools import batched
from uuid import UUID

from django.utils import timezone

from posthog.models import Organization

from products.signals.backend.rated_usage_models import SignalRatedUsage
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team

from ee.billing.billing_manager import BillingManager


class SignalsRatedUsageReporter:
    def report_day(self, organization_id: UUID, day: date) -> None:
        if day >= timezone.now().date():
            raise ValueError("Rated usage requires a closed UTC day")
        organization = Organization.objects.filter(id=organization_id).first()
        if organization is None:
            return
        begin = datetime.combine(day, time.min, UTC)
        credits = get_signals_spend_billing_credits_by_team(
            begin, begin + timedelta(days=1), organization_id=organization_id
        )
        SignalRatedUsage.objects.unscoped().bulk_create(
            [
                SignalRatedUsage(team_id=team_id, organization_id=organization_id, day=day, cents=cents)
                for team_id, cents in credits
            ],
            ignore_conflicts=True,
        )
        # Snapshot the customer and amount before POST so retries survive project moves.
        deliveries = (
            SignalRatedUsage.objects.unscoped()
            .filter(organization_id=organization_id, day=day)
            .order_by("team_id")
            .values_list("team_id", "cents")
        )
        # Grant allocation belongs to the trial integration. This path reports all metered usage as billable.
        items: list[dict[str, str | int]] = [
            {"team_id": team_id, "product": "inbox_usage", "day": day.isoformat(), "cents": cents}
            for team_id, cents in deliveries
        ]
        manager = BillingManager(None)
        for batch in batched(items, 1000, strict=False):
            manager.record_rated_usage(organization, list(batch))
            SignalRatedUsage.objects.unscoped().filter(
                organization_id=organization_id,
                day=day,
                team_id__in=[item["team_id"] for item in batch],
                reported_at__isnull=True,
            ).update(reported_at=timezone.now())
