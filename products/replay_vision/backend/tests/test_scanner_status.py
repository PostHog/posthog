import datetime as dt
from dataclasses import replace

from parameterized import parameterized

from products.replay_vision.backend.scanner_status import (
    ScannerStatus,
    ScannerStatusInputs,
    ScannerStatusReason,
    ScannerStatusResult,
    scanner_status,
)

NOW = dt.datetime(2026, 5, 12, 12, tzinfo=dt.UTC)

HEALTHY = ScannerStatusInputs(
    enabled=True,
    disabled_reason=None,
    sampling_rate=1.0,
    limit_reached=False,
    stopped_by_free_credits=False,
    has_filter_error=False,
    sweep_interval=dt.timedelta(minutes=5),
    sweep_pause_reason="",
    created_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
    last_swept_at=NOW - dt.timedelta(minutes=40),
    throttle_factor=1,
)


def _created_minutes_ago(minutes: int) -> dict:
    # A new scanner's watermark starts one settle window before creation and moves once a sweep finishes.
    return {
        "created_at": NOW - dt.timedelta(minutes=minutes),
        "last_swept_at": NOW - dt.timedelta(minutes=minutes + 35),
    }


class TestScannerStatus:
    @parameterized.expand(
        [
            ("running", {}, ScannerStatus.RUNNING, None),
            (
                "off wins over a limit and carries its reason",
                {"enabled": False, "disabled_reason": "no_ai_consent", "limit_reached": True},
                ScannerStatus.OFF,
                ScannerStatusReason.NO_AI_CONSENT,
            ),
            ("off with no recorded reason", {"enabled": False}, ScannerStatus.OFF, None),
            ("no sampling", {"sampling_rate": 0.0}, ScannerStatus.NO_SAMPLING, None),
            (
                "an own credit limit",
                {"limit_reached": True},
                ScannerStatus.LIMIT_REACHED,
                ScannerStatusReason.CREDIT_LIMIT,
            ),
            (
                "the free credits",
                {"limit_reached": True, "stopped_by_free_credits": True},
                ScannerStatus.LIMIT_REACHED,
                ScannerStatusReason.FREE_CREDITS_USED,
            ),
            (
                "a filter error ahead of the pause it causes",
                {"has_filter_error": True, "sweep_interval": None, "sweep_pause_reason": "filter_error"},
                ScannerStatus.FILTER_ERROR,
                None,
            ),
            (
                "paused ahead of the delay a paused sweep would otherwise read as",
                {
                    "sweep_interval": None,
                    "sweep_pause_reason": "experiment_not_running",
                    "last_swept_at": NOW - dt.timedelta(hours=3),
                },
                ScannerStatus.PAUSED,
                ScannerStatusReason.EXPERIMENT_NOT_RUNNING,
            ),
            ("starting while the first sweep runs", _created_minutes_ago(10), ScannerStatus.STARTING, None),
            ("delayed once the first sweep is overdue", _created_minutes_ago(70), ScannerStatus.DELAYED, None),
            ("delayed", {"last_swept_at": NOW - dt.timedelta(hours=3)}, ScannerStatus.DELAYED, None),
            (
                "not delayed while a low-yield sweep waits out its hourly interval",
                {"sweep_interval": dt.timedelta(minutes=60), "last_swept_at": NOW - dt.timedelta(hours=2)},
                ScannerStatus.RUNNING,
                None,
            ),
            (
                "throttled",
                {"throttle_factor": 3, "sweep_interval": dt.timedelta(minutes=15)},
                ScannerStatus.THROTTLED,
                None,
            ),
        ]
    )
    def test_status(
        self, _name: str, overrides: dict, status: ScannerStatus, reason: ScannerStatusReason | None
    ) -> None:
        assert scanner_status(replace(HEALTHY, **overrides), NOW) == ScannerStatusResult(status=status, reason=reason)
