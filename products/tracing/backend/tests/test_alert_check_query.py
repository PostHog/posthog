import base64
import datetime as dt
from datetime import UTC

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.tracing.backend.alert_check_query import AlertCheckQuery, _rolling_check_ranges
from products.tracing.backend.models import TracingAlertConfiguration

BASE = dt.datetime(2026, 6, 2, 8, 0, 0, tzinfo=UTC)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class TestAlertCheckQuery(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        def _row(uuid_suffix: int, ts: dt.datetime, service_name: str, status_code: int) -> str:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
            span_id = _b64(uuid_suffix.to_bytes(8, "big"))
            return (
                "("
                f"'019e8754-0000-0000-0000-{uuid_suffix:012d}', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
                f"'{span_id}', '', 'op', 2, '{ts_str}', '{ts_str}', '{ts_str}', {status_code}, '{service_name}'"
                ")"
            )

        # 3 "web" spans at minutes 0/1/2, 2 "worker" spans at minutes 0/1, 1 error span at minute 2.
        rows = [
            _row(1, BASE, "web", 0),
            _row(2, BASE + dt.timedelta(minutes=1), "web", 0),
            _row(3, BASE + dt.timedelta(minutes=2), "web", 2),
            _row(4, BASE, "worker", 0),
            _row(5, BASE + dt.timedelta(minutes=1), "worker", 0),
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    def _alert(self, **filters) -> TracingAlertConfiguration:
        return TracingAlertConfiguration(team=self.team, name="Test alert", threshold_count=1, filters=filters)

    @parameterized.expand(
        [
            ("unfiltered_counts_every_span", {}, 5),
            ("service_name_restricts_to_matching_spans", {"serviceNames": ["web"]}, 3),
            ("service_name_with_no_match_is_zero", {"serviceNames": ["does-not-exist"]}, 0),
            ("error_only_restricts_to_error_status", {"errorOnly": True}, 1),
        ]
    )
    def test_execute_counts_matching_spans(self, _name, filters, expected_count):
        query = AlertCheckQuery(
            team=self.team,
            alert=self._alert(**filters),
            date_from=BASE - dt.timedelta(minutes=1),
            date_to=BASE + dt.timedelta(minutes=5),
        )
        result = query.execute()
        assert result.count == expected_count

    def test_execute_rolling_checks_splits_counts_by_window(self):
        # 3 one-minute cadence-stepped windows ending at BASE + 3min: each window is
        # 1 minute wide, so it isolates exactly the spans at minutes 0, 1, and 2.
        query = AlertCheckQuery(
            team=self.team,
            alert=self._alert(serviceNames=["web"]),
            date_from=BASE - dt.timedelta(minutes=1),
            date_to=BASE + dt.timedelta(minutes=5),
        )
        buckets = query.execute_rolling_checks(
            nca=BASE + dt.timedelta(minutes=3),
            window_minutes=1,
            cadence_minutes=1,
            period_count=3,
        )
        assert [b.count for b in buckets] == [1, 1, 1]

    def test_team_mismatch_raises(self):
        other_team_alert = TracingAlertConfiguration(team_id=self.team.id + 1, name="Other team", threshold_count=1)
        try:
            AlertCheckQuery(team=self.team, alert=other_team_alert, date_from=BASE, date_to=BASE)
        except ValueError as e:
            assert "belongs to team" in str(e)
        else:
            raise AssertionError("expected ValueError")


class TestRollingCheckRanges:
    def test_ranges_are_oldest_first_and_cadence_stepped(self):
        nca = BASE + dt.timedelta(minutes=10)
        ranges = _rolling_check_ranges(nca, window_minutes=5, cadence_minutes=2, period_count=3)
        assert ranges == [
            (nca - dt.timedelta(minutes=9), nca - dt.timedelta(minutes=4)),
            (nca - dt.timedelta(minutes=7), nca - dt.timedelta(minutes=2)),
            (nca - dt.timedelta(minutes=5), nca - dt.timedelta(minutes=0)),
        ]
