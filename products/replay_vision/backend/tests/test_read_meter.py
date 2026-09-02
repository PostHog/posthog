import datetime as dt

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.replay_vision.backend.temporal.activities.meter_scanner_reads import meter_scanner_read_bytes_activity
from products.replay_vision.backend.temporal.constants import (
    DEEP_SPEND_WINDOW_DAYS,
    DEEP_SWEEP_INTERVAL,
    DEEP_SWEEP_MAX_FACTOR,
    DEEP_SWEEP_MAX_WINDOW,
    DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY,
    SWEEP_READ_BUDGET_BYTES_24H,
)
from products.replay_vision.backend.temporal.read_meter_types import (
    deep_spend_bytes_per_day,
    deep_sweep_throttle_factor,
    sweep_spend_bytes_24h,
    sweep_throttle_factor,
)

_NOW = dt.datetime(2026, 8, 12, 12, 0, 0, tzinfo=dt.UTC)


def _hour(hours_ago: int) -> str:
    return (_NOW - dt.timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0).isoformat()


class TestDeepSweepCadenceInvariant:
    def test_a_pass_covers_more_ground_than_the_gap_before_it(self) -> None:
        # The one invariant tying the two constants together. Stretch the cadence past the ground one
        # pass covers and the watermark loses the difference every time, permanently, until it is far
        # enough behind that the recordings it reaches have aged out and the pass finds nothing.
        longest_gap = DEEP_SWEEP_INTERVAL * DEEP_SWEEP_MAX_FACTOR
        assert DEEP_SWEEP_MAX_WINDOW > longest_gap


class TestThrottleMath:
    @parameterized.expand(
        [
            ("under_budget", SWEEP_READ_BUDGET_BYTES_24H // 2, None, 1),
            ("at_budget", SWEEP_READ_BUDGET_BYTES_24H, None, 1),
            # Just over the budget still has to throttle; nearest-rounding used to let this run free.
            ("just_over_budget", SWEEP_READ_BUDGET_BYTES_24H + 1, None, 2),
            ("well_under_one_and_a_half", int(SWEEP_READ_BUDGET_BYTES_24H * 1.25), None, 2),
            ("ten_times_budget", SWEEP_READ_BUDGET_BYTES_24H * 10, None, 10),
            ("capped_at_max", SWEEP_READ_BUDGET_BYTES_24H * 100, None, 12),
            ("override_wins_over_spend", SWEEP_READ_BUDGET_BYTES_24H * 100, 1, 1),
            ("override_forces_throttle", 0, 6, 6),
            ("override_capped", 0, 99, 12),
        ]
    )
    def test_sweep_throttle_factor(self, _name: str, spend: int, override: int | None, expected: int) -> None:
        assert sweep_throttle_factor(spend, override) == expected

    @parameterized.expand(
        [
            ("under_budget", DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY // 2, 1),
            ("just_over_budget", DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY + 1, 2),
            # Capped lower than the frequent sweep's ceiling, deliberately: the deep pass cannot be
            # stretched past the ground one pass covers without falling behind for good.
            ("over_budget_hits_the_deep_cap", DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY * 10, DEEP_SWEEP_MAX_FACTOR),
            ("far_over_budget_stays_capped", DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY * 500, DEEP_SWEEP_MAX_FACTOR),
        ]
    )
    def test_deep_sweep_throttle_factor(self, _name: str, spend: int, expected: int) -> None:
        assert deep_sweep_throttle_factor(spend) == expected

    def test_deep_spend_survives_longer_than_the_interval_it_sets(self) -> None:
        # A pass stretched past a day writes one bucket and then has to stay priced by it. Measuring
        # over 24h instead would let that bucket age out, collapse the factor to 1, and cap the real
        # cadence near a day however high the ceiling is set.
        # Sized like the scanners this exists for: one pass costing ~150x the daily budget.
        one_pass = {_hour(72): SWEEP_READ_BUDGET_BYTES_24H * 150}

        assert sweep_spend_bytes_24h(one_pass, _NOW) == 0
        rate = deep_spend_bytes_per_day(one_pass, _NOW)
        assert rate == SWEEP_READ_BUDGET_BYTES_24H * 150 // DEEP_SPEND_WINDOW_DAYS
        assert deep_sweep_throttle_factor(rate) == DEEP_SWEEP_MAX_FACTOR

    def test_deep_spend_drops_out_past_the_pricing_window(self) -> None:
        # Otherwise a scanner stays throttled on spend it no longer incurs.
        assert deep_spend_bytes_per_day({_hour(24 * DEEP_SPEND_WINDOW_DAYS + 1): 10**12}, _NOW) == 0

    def test_spend_sums_only_trailing_24h_and_tolerates_junk(self) -> None:
        buckets = {
            _hour(1): 100,
            _hour(23): 200,
            _hour(30): 4_000_000,  # stale, unpruned — must not count
            "not-a-timestamp": 5_000_000,
        }
        assert sweep_spend_bytes_24h(buckets, _NOW) == 300

    def test_naive_bucket_key_is_treated_as_utc_not_raised(self) -> None:
        # This runs inside the sweep, so raising here would stop the scanner rather than mis-report it.
        naive = (_NOW - dt.timedelta(hours=1)).replace(tzinfo=None).isoformat()
        assert sweep_spend_bytes_24h({naive: 7}, _NOW) == 7

    def test_spend_of_empty_buckets_is_zero(self) -> None:
        assert sweep_spend_bytes_24h(None, _NOW) == 0
        assert sweep_spend_bytes_24h({}, _NOW) == 0


@pytest.mark.django_db(transaction=True)
class TestMeterScannerReadsActivity:
    def test_the_metering_sql_executes_against_clickhouse(self) -> None:
        # Every other test here mocks sync_execute, which is how an alias-shadowing SQL error once
        # shipped and failed every production metering run; this executes the real query.
        result = meter_scanner_read_bytes_activity()

        assert result.scanners_updated == 0

    def test_junk_scanner_tag_does_not_take_down_the_run(self) -> None:
        # scanner_id is a free-form string in the query log, so a non-UUID must be skipped rather
        # than blowing up the pk__in lookup for every other scanner in the batch.
        from products.replay_vision.backend.tests.test_sweep import _make_scanner

        scanner = _make_scanner()
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
        with patch(
            "products.replay_vision.backend.temporal.activities.meter_scanner_reads.sync_execute",
            return_value=[
                ("not-a-uuid", hour.replace(tzinfo=None), 11, 0, 0),
                (str(scanner.id), hour.replace(tzinfo=None), 22, 7, 15),
            ],
        ):
            result = meter_scanner_read_bytes_activity()

        assert result.scanners_updated == 1
        scanner.refresh_from_db()
        assert scanner.sweep_read_bytes_by_hour == {hour.isoformat(): 22}
        # Deep spend is metered separately so it can stretch the deep interval without
        # dragging the frequent sweep's cadence down with it.
        assert scanner.deep_read_bytes_by_hour == {hour.isoformat(): 7}
        # Metered, not derived: the 22 total includes backfill reads that must not reach this bucket.
        assert scanner.fast_read_bytes_by_hour == {hour.isoformat(): 15}

    def test_folds_query_log_rows_into_hour_buckets_and_prunes(self) -> None:
        from products.replay_vision.backend.tests.test_sweep import _make_scanner

        scanner = _make_scanner()
        stale_hour = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)).isoformat()
        fresh_hour = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        scanner.sweep_read_bytes_by_hour = {stale_hour: 999, fresh_hour.isoformat(): 50}
        scanner.save(update_fields=["sweep_read_bytes_by_hour"])

        current_hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
        with patch(
            "products.replay_vision.backend.temporal.activities.meter_scanner_reads.sync_execute",
            return_value=[
                # Re-scanned bucket overwrites (never sums with) the stored value for the same hour.
                (str(scanner.id), fresh_hour.replace(tzinfo=None), 70, 0, 70),
                (str(scanner.id), current_hour.replace(tzinfo=None), 40, 0, 40),
                ("00000000-0000-0000-0000-000000000000", current_hour.replace(tzinfo=None), 123, 0, 123),
            ],
        ):
            result = meter_scanner_read_bytes_activity()

        assert result.scanners_updated == 1
        scanner.refresh_from_db()
        # Every mocked row here has zero deep spend, and zeros are not stored: keeping them would
        # double this table's hourly write volume for the scanners that never run a deep pass.
        assert scanner.deep_read_bytes_by_hour == {}
        assert scanner.sweep_read_bytes_by_hour == {
            fresh_hour.isoformat(): 70,
            current_hour.isoformat(): 40,
        }
