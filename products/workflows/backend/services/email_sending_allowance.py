from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_team_and_source
from posthog.dataclasses import frozen

from products.workflows.backend.utils.email_sending_tiers import max_email_sending_tier, resolve_team_email_sending_tier

SENDING_ALLOWANCE_CACHE_SECONDS = 60


@frozen
class EmailSendingAllowance:
    """A project's sending tier, what it allows, and how much of that it has used."""

    tier: int
    max_tier: int
    emails_per_hour: int
    emails_per_day: int
    max_batch_audience: int
    emails_sent_last_hour: int
    emails_sent_last_day: int
    enforced: bool

    @property
    def daily_cap_reached(self) -> bool:
        return self.enforced and self.emails_sent_last_day >= self.emails_per_day


def team_email_sending_allowance(team_id: int) -> EmailSendingAllowance:
    """
    Usage comes from the send metrics rather than the worker's token buckets, so the numbers match
    what the rest of this page reports. Cached briefly because the endpoint reloads on every search
    keystroke while these two aggregations do not depend on the search.
    """
    # Versioned because the cached dataclass moved modules, and older pickles cannot load.
    cache_key = f"workflows_email_sending_allowance_v2_{team_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resolved = resolve_team_email_sending_tier(team_id)
    now = timezone.now()
    allowance = EmailSendingAllowance(
        tier=resolved.tier,
        max_tier=max_email_sending_tier(),
        emails_per_hour=resolved.limits.per_hour,
        emails_per_day=resolved.limits.per_day,
        max_batch_audience=resolved.limits.max_batch_audience,
        emails_sent_last_hour=_team_email_sends_since(team_id, now - timedelta(hours=1)),
        emails_sent_last_day=_team_email_sends_since(team_id, now - timedelta(days=1)),
        enforced=resolved.enforced,
    )
    cache.set(cache_key, allowance, SENDING_ALLOWANCE_CACHE_SECONDS)
    return allowance


def _team_email_sends_since(team_id: int, after: datetime) -> int:
    totals = fetch_app_metric_totals_by_team_and_source(
        app_source="hog_flow", name=["email_sent"], after=after, team_ids=[team_id]
    )
    return sum(counts.get("email_sent", 0) for counts in totals.get(team_id, {}).values())
