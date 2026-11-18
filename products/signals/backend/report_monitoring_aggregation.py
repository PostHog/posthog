from collections.abc import Collection
from enum import StrEnum

from django.db import models


class MonitoringMemberState(StrEnum):
    WAITING = "waiting"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    EXHAUSTED = "exhausted"


class MonitoringAggregation(models.TextChoices):
    WAITING = "waiting"
    PASSED = "passed"
    FAILED = "failed"
    ASSESSMENT_REQUIRED = "assessment_required"


def aggregate_monitoring_members(members: Collection[MonitoringMemberState]) -> MonitoringAggregation:
    states = frozenset(members)
    if MonitoringMemberState.FAILED in states:
        return MonitoringAggregation.FAILED
    if not states or MonitoringMemberState.WAITING in states:
        return MonitoringAggregation.WAITING
    if states == {MonitoringMemberState.PASSED}:
        return MonitoringAggregation.PASSED
    return MonitoringAggregation.ASSESSMENT_REQUIRED
