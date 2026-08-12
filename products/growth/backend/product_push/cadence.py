"""Cadence rules for organization product push campaigns.

Pure date math — no DB access — so the rules are unit-testable in isolation.
Campaigns are rolling windows anchored on their own start (not on the org's
signup anniversary): the between-campaigns cooldown and early adoption closes
make anniversary anchoring impossible to keep.
"""

from datetime import date, datetime, timedelta

# No pushes for this long after the organization signs up.
GRACE_PERIOD_DAYS = 10

# How long a campaign keeps pushing before it is closed as skipped.
CAMPAIGN_DURATION_DAYS = 14

# Quiet period between one campaign ending (for any reason) and the next starting.
COOLDOWN_DAYS = 7

# A skipped (or cancelled) product becomes eligible to push again after this long.
# Deliberately short enough that blessed products keep cycling — an org that skips
# everything retries the blessed order rather than draining the fallback pool.
SKIP_RETRY_DAYS = 90


def campaign_ends_at(started_at: datetime) -> datetime:
    return started_at + timedelta(days=CAMPAIGN_DURATION_DAYS)


def is_grace_period_over(organization_created_at: datetime, now: datetime) -> bool:
    return now >= organization_created_at + timedelta(days=GRACE_PERIOD_DAYS)


def is_cooldown_over(last_campaign_ended_at: datetime | None, now: datetime) -> bool:
    if last_campaign_ended_at is None:
        return True
    return now >= last_campaign_ended_at + timedelta(days=COOLDOWN_DAYS)


def is_pin_due(scheduled_for: date | None, now: datetime) -> bool:
    """An unset pin is always due; a dated pin is due from that date onward."""
    if scheduled_for is None:
        return True
    return now.date() >= scheduled_for


def is_retry_eligible(campaign_ended_at: datetime, now: datetime) -> bool:
    return now >= campaign_ended_at + timedelta(days=SKIP_RETRY_DAYS)
