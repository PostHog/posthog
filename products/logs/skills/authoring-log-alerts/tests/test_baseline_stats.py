"""End-to-end tests for the alert authoring baseline_stats helper script."""

from __future__ import annotations

import sys
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "baseline_stats.py"


def _bucket(date_from: str, date_to: str, count: int) -> dict:
    return {"date_from": date_from, "date_to": date_to, "count": count}


def _run(payload: dict | str, *args: str) -> tuple[int, dict | None, str]:
    """Run the script with a JSON payload on stdin and return (exit_code, parsed_stdout, stderr)."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=body,
        capture_output=True,
        text=True,
        timeout=10,
    )
    parsed: dict | None = None
    if result.returncode == 0 and result.stdout.strip():
        parsed = json.loads(result.stdout)
    return result.returncode, parsed, result.stderr


_BUCKETS_BASE = datetime(2026, 4, 22)


def _seven_hour_buckets(counts: list[int]) -> list[dict]:
    """Build 7h buckets starting 2026-04-22T00:00:00."""
    return [
        _bucket(
            (_BUCKETS_BASE + timedelta(hours=i * 7)).isoformat(),
            (_BUCKETS_BASE + timedelta(hours=(i + 1) * 7)).isoformat(),
            c,
        )
        for i, c in enumerate(counts)
    ]


class TestHealthyBaseline:
    def test_spiky_baseline_returns_threshold_and_no_critical_health_flags(self) -> None:
        counts = [10, 12, 15, 11, 140, 13, 9, 11, 14, 10, 13, 12]
        code, out, err = _run({"ranges": _seven_hour_buckets(counts), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0, err
        assert out is not None
        assert out["n_buckets"] == 12
        assert out["bucket_minutes"] == 420.0
        assert out["alert_window_minutes"] == 5
        assert out["stats"]["max"] == 140
        assert out["stats"]["p50"] == 12.0
        assert out["stats"]["p95"] > out["stats"]["p50"]
        assert out["suggested_threshold_count"] >= 5  # floor enforced
        assert "empty" not in out["health"]
        assert "sparse:" not in " ".join(out["health"])

    def test_rationale_includes_terms(self) -> None:
        counts = [10, 12, 15, 11, 140, 13, 9, 11, 14, 10, 13, 12]
        code, out, _ = _run({"ranges": _seven_hour_buckets(counts), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0
        assert out is not None
        assert "p99" in out["rationale"]
        assert "median*3" in out["rationale"]
        assert "floor" in out["rationale"]


class TestHealthFlags:
    def test_sparse_flag_when_fewer_than_min_buckets(self) -> None:
        code, out, _ = _run({"ranges": _seven_hour_buckets([10, 12]), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0
        assert out is not None
        assert any(flag.startswith("sparse:2_of_12_buckets") for flag in out["health"])

    def test_sparse_flag_respects_min_buckets_override(self) -> None:
        code, out, _ = _run(
            {"ranges": _seven_hour_buckets([10, 12, 11]), "interval": "7h"},
            "--window-minutes",
            "5",
            "--min-buckets",
            "2",
        )

        assert code == 0
        assert out is not None
        assert not any(flag.startswith("sparse:") for flag in out["health"])

    def test_empty_flag_when_all_buckets_zero(self) -> None:
        code, out, _ = _run({"ranges": _seven_hour_buckets([0] * 24), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0
        assert out is not None
        assert "empty" in out["health"]

    def test_flat_flag_when_p95_close_to_median(self) -> None:
        counts = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11]
        code, out, _ = _run({"ranges": _seven_hour_buckets(counts), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0
        assert out is not None
        assert "flat" in out["health"]
        assert "spiky" not in out["health"]

    def test_spiky_flag_when_max_dwarfs_p95(self) -> None:
        # 23 quiet buckets at ~10, one massive spike — pushes max/p95 over 10×.
        counts = [10] * 23 + [500]
        code, out, _ = _run({"ranges": _seven_hour_buckets(counts), "interval": "7h"}, "--window-minutes", "5")

        assert code == 0
        assert out is not None
        assert "spiky" in out["health"]
        assert "flat" not in out["health"]


class TestWindowScaling:
    def test_thirty_minute_window_yields_six_times_the_five_minute_threshold(self) -> None:
        # Same data, different window. With a 7h bucket and rate-uniform scaling,
        # a 30m window should be 6× the 5m suggestion (modulo floor and rounding).
        counts = [100] * 12 + [10000]  # one big spike — ensures the suggestion is well above floor
        ranges = _seven_hour_buckets(counts)

        code_5, out_5, _ = _run({"ranges": ranges}, "--window-minutes", "5")
        code_30, out_30, _ = _run({"ranges": ranges}, "--window-minutes", "30")

        assert code_5 == 0 and code_30 == 0
        assert out_5 is not None and out_30 is not None
        # Allow a few units of rounding noise — ratio should be ~6.
        ratio = out_30["suggested_threshold_count"] / out_5["suggested_threshold_count"]
        assert 5.5 <= ratio <= 6.5, f"expected ~6× scaling, got {ratio}"

    def test_floor_dominates_when_data_is_tiny(self) -> None:
        code, out, _ = _run(
            {"ranges": _seven_hour_buckets([1, 2, 1, 2] * 3), "interval": "7h"},
            "--window-minutes",
            "5",
        )

        assert code == 0
        assert out is not None
        assert out["suggested_threshold_count"] == 5  # floor wins on tiny-count data

    def test_custom_floor_is_respected(self) -> None:
        code, out, _ = _run(
            {"ranges": _seven_hour_buckets([1] * 12), "interval": "7h"},
            "--window-minutes",
            "5",
            "--floor",
            "20",
        )

        assert code == 0
        assert out is not None
        assert out["suggested_threshold_count"] == 20


class TestErrorPaths:
    def test_empty_ranges_returns_error(self) -> None:
        code, out, err = _run({"ranges": [], "interval": "7h"}, "--window-minutes", "5")

        assert code == 1
        assert out is None
        assert "no buckets" in err.lower()

    def test_missing_ranges_key_returns_error(self) -> None:
        code, _, err = _run({"interval": "7h"}, "--window-minutes", "5")

        assert code == 1
        assert "no buckets" in err.lower()

    def test_malformed_json_returns_error(self) -> None:
        code, _, err = _run("not json at all", "--window-minutes", "5")

        assert code == 1
        assert "json" in err.lower()

    def test_invalid_window_minutes_rejected_by_argparse(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--window-minutes", "7"],
            input="{}",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower()

    def test_missing_count_field_in_buckets(self) -> None:
        code, _, err = _run({"ranges": [{"date_from": "x", "date_to": "y"}]}, "--window-minutes", "5")

        assert code == 1
        assert "count" in err.lower()

    def test_iso_timestamp_with_z_suffix(self) -> None:
        # Some clients format ISO with trailing Z; the script should tolerate it.
        ranges = [
            _bucket("2026-04-22T00:00:00Z", "2026-04-22T07:00:00Z", 50),
            _bucket("2026-04-22T07:00:00Z", "2026-04-22T14:00:00Z", 60),
        ]
        code, out, err = _run({"ranges": ranges}, "--window-minutes", "5", "--min-buckets", "2")

        assert code == 0, err
        assert out is not None
        assert out["bucket_minutes"] == 420.0


@pytest.mark.parametrize(
    "window_minutes",
    [5, 10, 15, 30, 60],
)
def test_all_allowed_windows_accepted(window_minutes: int) -> None:
    counts = [10, 12, 15, 11, 13, 9, 11, 14, 10, 13, 12, 11]
    code, out, _ = _run(
        {"ranges": _seven_hour_buckets(counts), "interval": "7h"}, "--window-minutes", str(window_minutes)
    )

    assert code == 0
    assert out is not None
    assert out["alert_window_minutes"] == window_minutes
