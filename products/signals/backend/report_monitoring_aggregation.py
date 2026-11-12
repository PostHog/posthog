from collections.abc import Collection
from enum import StrEnum

from django.db import models


class MonitoringMemberState(StrEnum):
    WAITING = "waiting"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"


class MonitoringAggregation(models.TextChoices):
    WAITING = "waiting"
    PASSED = "passed"
    FAILED = "failed"
    ASSESSMENT_REQUIRED = "assessment_required"


def aggregate_monitoring_members(members: Collection[MonitoringMemberState]) -> MonitoringAggregation:
    # A cancelled check leaves the snapshot. With none left, the report resolves as if it never had checks.
    states = frozenset(members) - {MonitoringMemberState.CANCELLED}
    if MonitoringMemberState.FAILED in states:
        return MonitoringAggregation.FAILED
    if not states:
        return MonitoringAggregation.PASSED if members else MonitoringAggregation.WAITING
    if MonitoringMemberState.WAITING in states:
        return MonitoringAggregation.WAITING
    if states == {MonitoringMemberState.PASSED}:
        return MonitoringAggregation.PASSED
    return MonitoringAggregation.ASSESSMENT_REQUIRED
