"""Where a theme or group stands, from its first and last member and how its members split across recent weeks.

The state is derived on read from the cluster row and its day counts, so it never goes stale and needs no job.
A person's review takes precedence, except that new members after `resolved` reopen it as a regression.
"""

from datetime import datetime, timedelta

from django.db import models

from products.replay_vision.backend.models.replay_scanner_semantics import ClusterReview

# A cluster this young is still forming, whatever its size.
EMERGING_AGE = timedelta(days=7)
# With no member for this long, a cluster no longer describes something people run into.
DORMANT_AFTER = timedelta(days=14)
# Last week's members below this share of the week before mean the problem is fading.
FADING_SHARE = 0.5


class ClusterStatus(models.TextChoices):
    EMERGING = "emerging"
    ACTIVE = "active"
    FADING = "fading"
    DORMANT = "dormant"
    KNOWN = "known"
    RESOLVED = "resolved"
    REGRESSED = "regressed"
    NOT_AN_ISSUE = "not_an_issue", "Not an issue"


def cluster_status(
    *,
    now: datetime,
    first_member_at: datetime,
    last_member_at: datetime,
    last_week: int,
    week_before: int,
    review_state: str,
    reviewed_at: datetime | None,
) -> ClusterStatus:
    if review_state == ClusterReview.RESOLVED:
        regressed = reviewed_at is not None and last_member_at > reviewed_at
        return ClusterStatus.REGRESSED if regressed else ClusterStatus.RESOLVED
    if review_state == ClusterReview.NOT_AN_ISSUE:
        return ClusterStatus.NOT_AN_ISSUE
    if review_state == ClusterReview.KNOWN:
        return ClusterStatus.KNOWN
    if now - last_member_at >= DORMANT_AFTER:
        return ClusterStatus.DORMANT
    if now - first_member_at < EMERGING_AGE:
        return ClusterStatus.EMERGING
    if week_before > 0 and last_week < week_before * FADING_SHARE:
        return ClusterStatus.FADING
    return ClusterStatus.ACTIVE
