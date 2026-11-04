"""Self-driving quota and free trial gates for products that start pull request work from a report.

Each function calls its implementation through the module attribute, so a test that patches the
implementation also changes what callers of this facade see.
"""

from typing import TYPE_CHECKING

from products.signals.backend import free_trial, quota
from products.signals.backend.free_trial import FreeTrialPullRequestRefused
from products.signals.backend.quota import SelfDrivingQuotaGate

if TYPE_CHECKING:
    from posthog.models import Team

__all__ = [
    "FreeTrialPullRequestRefused",
    "SelfDrivingQuotaGate",
    "capture_signal_report_free_trial_paused",
    "capture_signal_report_quota_paused",
    "record_quota_check_failed_open",
    "self_driving_free_trial_enabled",
    "self_driving_quota_gate",
]


def self_driving_quota_gate(team: "Team") -> SelfDrivingQuotaGate:
    return quota.self_driving_quota_gate(team)


def capture_signal_report_quota_paused(team: "Team", *, report_id: str | None, stage: str, enforced: bool) -> None:
    quota.capture_signal_report_quota_paused(team, report_id=report_id, stage=stage, enforced=enforced)


def record_quota_check_failed_open() -> None:
    quota.record_quota_check_failed_open()


def self_driving_free_trial_enabled(team: "Team") -> bool:
    return free_trial.self_driving_free_trial_enabled(team)


def capture_signal_report_free_trial_paused(team: "Team", *, report_id: str | None, stage: str) -> None:
    free_trial.capture_signal_report_free_trial_paused(team, report_id=report_id, stage=stage)
