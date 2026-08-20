import datetime as dt

import pytest
from unittest.mock import patch

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.activities.auto_materialize import (
    AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES,
    auto_materialize_scanner_properties_activity,
)
from products.replay_vision.backend.tests.test_sweep import _make_scanner

_MOD = "products.replay_vision.backend.temporal.activities.auto_materialize"

_QUERY_WITH_EVENT_FILTERS = {
    "kind": "RecordingsQuery",
    "properties": [
        {"type": "feature", "key": "$feature/expensive-flag", "operator": "exact", "value": ["true"]},
        {"type": "person", "key": "email", "operator": "icontains", "value": "@example.com"},
    ],
    "events": [
        {
            "id": "$pageview",
            "type": "events",
            "properties": [{"type": "event", "key": "plan_tier", "operator": "exact", "value": "enterprise"}],
        }
    ],
    "actions": [
        {
            "id": 42,
            "type": "actions",
            "properties": [{"type": "event", "key": "checkout_step", "operator": "exact", "value": "3"}],
        }
    ],
}


def _spendy_scanner(spend_bytes: int, query: dict | None = None) -> ReplayScanner:
    hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
    return _make_scanner(query=query or _QUERY_WITH_EVENT_FILTERS, fast_read_bytes_by_hour={hour: spend_bytes})


def _run(*, enabled: bool = True, acting_hour: bool = True, already_materialized: frozenset[str] = frozenset()):
    hour_now = dt.datetime.now(dt.UTC).hour
    with (
        patch(f"{_MOD}.AUTO_MATERIALIZE_ENABLED", enabled),
        patch(f"{_MOD}._ACTING_HOUR_UTC", hour_now if acting_hour else (hour_now + 1) % 24),
        patch(f"{_MOD}.materialize_properties_task") as task,
        patch(
            f"{_MOD}.get_materialized_columns",
            return_value={(prop, "properties"): object() for prop in already_materialized},
        ),
    ):
        result = auto_materialize_scanner_properties_activity()
    return result, task


@pytest.mark.django_db(transaction=True)
class TestAutoMaterializeScannerProperties:
    def test_materializes_event_and_feature_filters_of_a_scanner_over_budget(self) -> None:
        _spendy_scanner(AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 2)

        result, task = _run()

        # Person-scoped filters never reach the events properties column, so they must not be proposed.
        assert sorted(task.call_args.kwargs["properties_to_materialize"]) == [
            ("events", "properties", "$feature/expensive-flag"),
            ("events", "properties", "checkout_step"),
        ]
        assert result.candidates == 3
        assert result.materialized == 2

    def test_a_scanner_under_the_spend_threshold_is_never_a_candidate(self) -> None:
        _spendy_scanner(AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES // 2)

        result, task = _run()

        task.assert_not_called()
        assert result.candidates == 0

    def test_backfill_spend_alone_does_not_qualify_a_scanner(self) -> None:
        # Backfill reads land only in the total bucket; a one-day backfill must not mint columns.
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        _make_scanner(
            query=_QUERY_WITH_EVENT_FILTERS,
            fast_read_bytes_by_hour={hour: AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES // 10},
            deep_read_bytes_by_hour={},
            sweep_read_bytes_by_hour={hour: AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 5},
        )

        result, task = _run()

        task.assert_not_called()
        assert result.candidates == 0

    def test_a_pre_split_scanner_with_only_the_total_bucket_never_qualifies(self) -> None:
        # A row the split meter has not written yet has both split buckets null; the total bucket
        # folds in backfill reads, so it must not qualify on that alone.
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        _make_scanner(
            query=_QUERY_WITH_EVENT_FILTERS,
            sweep_read_bytes_by_hour={hour: AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 5},
        )

        result, task = _run()

        task.assert_not_called()
        assert result.candidates == 0

    def test_flag_off_logs_candidates_but_creates_nothing(self) -> None:
        _spendy_scanner(AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 2)

        result, task = _run(enabled=False)

        task.assert_not_called()
        assert result.candidates == 3
        assert result.materialized == 0

    def test_a_property_key_unsafe_for_column_metadata_is_never_proposed(self) -> None:
        # Materialized-column metadata round-trips the key through a `::`-delimited comment, so a
        # hostile or accidental `::` key would poison every registry lookup cluster-wide.
        _spendy_scanner(
            AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 2,
            query={
                "kind": "RecordingsQuery",
                "properties": [{"type": "event", "key": "foo::bar", "operator": "exact", "value": "x"}],
            },
        )

        result, task = _run()

        task.assert_not_called()
        assert result.candidates == 0

    def test_outside_the_acting_hour_nothing_is_created(self) -> None:
        # The meter runs hourly; acting once a day is what bounds cluster-wide column growth.
        _spendy_scanner(AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 2)

        result, task = _run(acting_hour=False)

        task.assert_not_called()
        assert result.candidates == 3

    def test_already_materialized_properties_are_not_proposed_again(self) -> None:
        _spendy_scanner(AUTO_MATERIALIZE_MIN_DAILY_READ_BYTES * 2)

        result, task = _run(already_materialized=frozenset({"$feature/expensive-flag"}))

        assert sorted(task.call_args.kwargs["properties_to_materialize"]) == [
            ("events", "properties", "checkout_step"),
            ("events", "properties", "plan_tier"),
        ]
        assert result.materialized == 2
