import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.logs import LOGS34_TO_VOLUME_BUCKETS_MV

from products.logs.backend.temporal.volume_tick.aggregation import (
    _ENVIRONMENT_KEYS,
    _NAMESPACE_KEYS,
    RollupPreview,
    _rollup_parameters,
    _rollup_sql,
    preview_rollup,
)
from products.logs.backend.temporal.volume_tick.constants import BUCKET_SECONDS

_START = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
_END = _START + timedelta(seconds=BUCKET_SECONDS)


class TestVolumeBucketAggregation(ClickhouseTestMixin, BaseTest):
    def _insert_logs(self, rows: list[dict]) -> None:
        payload = "".join(json.dumps(row) + "\n" for row in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{payload}")

    def _log(
        self,
        at: datetime,
        *,
        service: str = "checkout",
        severity: str = "info",
        resource_attributes: dict[str, str] | None = None,
    ) -> dict:
        return {
            "uuid": str(uuid.uuid4()),
            "team_id": self.team.id,
            "timestamp": at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "body": "",
            "severity_text": severity,
            "severity_number": 9,
            "service_name": service,
            "resource_attributes": resource_attributes or {},
            "attributes_map_str": {},
        }

    def _rollup(self, *, start: datetime = _START, end: datetime = _END) -> list[tuple]:
        """The rows the rollup would write, ordered. Runs the writer's own query,
        so these assertions hold unchanged once it writes rather than counts."""
        rows = sync_execute(_rollup_sql(), _rollup_parameters([self.team.id], start, end))
        return sorted(rows, key=lambda row: (row[1], row[2], row[3], row[4], row[5]))

    def _preview(self, *, start: datetime = _START, end: datetime = _END) -> RollupPreview:
        return preview_rollup(team_ids=[self.team.id], start=start, end=end)

    def test_counts_match_a_direct_raw_query(self) -> None:
        self._insert_logs(
            [
                self._log(_START + timedelta(seconds=offset), service=service, severity=severity)
                for offset, service, severity in [
                    (0, "checkout", "info"),
                    (1, "checkout", "info"),
                    (2, "checkout", "error"),
                    (3, "search", "info"),
                ]
            ]
        )

        rolled_up = [(row[2], row[5], row[6]) for row in self._rollup()]
        direct = sync_execute(
            """
            SELECT service_name, lower(severity_text), count()
            FROM logs_distributed
            WHERE team_id = %(team_id)s AND timestamp >= %(start)s AND timestamp < %(end)s
            GROUP BY service_name, lower(severity_text)
            ORDER BY service_name, lower(severity_text)
            """,
            {"team_id": self.team.id, "start": _START, "end": _END},
        )
        # Both sides empty would compare equal and prove nothing.
        self.assertEqual(rolled_up, [("checkout", "error", 1), ("checkout", "info", 2), ("search", "info", 1)])
        self.assertEqual(rolled_up, [(row[0], row[1], row[2]) for row in direct])

    def test_preview_summarizes_the_rows_the_rollup_would_write(self) -> None:
        self._insert_logs(
            [
                self._log(_START, service="checkout", severity="info"),
                self._log(_START, service="checkout", severity="info"),
                self._log(_START, service="checkout", severity="error"),
                self._log(_START, service="search", severity="info"),
            ]
        )

        preview = self._preview()

        self.assertEqual(
            preview,
            RollupPreview(
                rollup_rows=3,
                source_rows=4,
                distinct_services=2,
                rows_without_namespace=3,
                rows_without_environment=3,
            ),
        )

    def test_preview_counts_resolved_dimensions_as_present(self) -> None:
        self._insert_logs(
            [
                self._log(_START, resource_attributes={"k8s.namespace.name": "web", "env": "prod"}),
                self._log(_START, service="search", resource_attributes={"k8s.namespace.name": "web"}),
            ]
        )

        preview = self._preview()

        self.assertEqual(preview.rows_without_namespace, 0)
        self.assertEqual(preview.rows_without_environment, 1)

    def test_preview_of_an_empty_window_is_all_zeroes(self) -> None:
        preview = self._preview()

        self.assertEqual(
            preview,
            RollupPreview(
                rollup_rows=0,
                source_rows=0,
                distinct_services=0,
                rows_without_namespace=0,
                rows_without_environment=0,
            ),
        )

    def test_logs_land_in_their_own_grid_bucket(self) -> None:
        second_bucket = _START + timedelta(seconds=BUCKET_SECONDS)
        self._insert_logs(
            [
                self._log(second_bucket - timedelta(seconds=1)),
                self._log(second_bucket),
            ]
        )
        window = {"start": _START, "end": second_bucket + timedelta(seconds=BUCKET_SECONDS)}

        rows = self._rollup(**window)

        # Aware, and UTC: the grid pins its timezone rather than inheriting the session's.
        self.assertEqual([(row[1], row[6]) for row in rows], [(_START, 1), (second_bucket, 1)])
        self.assertEqual([row[1].utcoffset() for row in rows], [timedelta(0)] * 2)
        self.assertEqual(self._preview(**window).rollup_rows, 2)

    @parameterized.expand(
        [
            ("current_semconv", {"deployment.environment.name": "prod"}, "prod"),
            ("previous_semconv", {"deployment.environment": "prod"}, "prod"),
            ("datadog_tag", {"env": "prod"}, "prod"),
            ("current_wins_over_older", {"deployment.environment.name": "prod", "env": "staging"}, "prod"),
            ("absent", {}, ""),
        ]
    )
    def test_environment_falls_back_through_the_key_chain(
        self, _name: str, resource_attributes: dict[str, str], expected: str
    ) -> None:
        self._insert_logs([self._log(_START, resource_attributes=resource_attributes)])

        self.assertEqual([row[4] for row in self._rollup()], [expected])

    @parameterized.expand(
        [
            ("k8s", {"k8s.namespace.name": "web"}, "web"),
            ("non_k8s_semconv", {"service.namespace": "web"}, "web"),
            ("k8s_wins_when_both", {"k8s.namespace.name": "web", "service.namespace": "team-a"}, "web"),
            ("absent", {}, ""),
        ]
    )
    def test_namespace_falls_back_through_the_key_chain(
        self, _name: str, resource_attributes: dict[str, str], expected: str
    ) -> None:
        self._insert_logs([self._log(_START, resource_attributes=resource_attributes)])

        self.assertEqual([row[3] for row in self._rollup()], [expected])

    def test_severity_casing_merges_into_one_series(self) -> None:
        self._insert_logs([self._log(_START, severity="ERROR"), self._log(_START, severity="error")])

        self.assertEqual([(row[5], row[6]) for row in self._rollup()], [("error", 2)])

    @parameterized.expand(
        [
            ("no_teams", [], _START, _END),
            ("naive_start", [1], _START.replace(tzinfo=None), _END),
            ("naive_end", [1], _START, _END.replace(tzinfo=None)),
            ("end_before_start", [1], _END, _START),
            ("empty_window", [1], _START, _START),
            ("unaligned_start", [1], _START + timedelta(seconds=1), _END),
            ("unaligned_end", [1], _START, _END + timedelta(seconds=1)),
        ]
    )
    def test_rejects_invalid_input(self, _name: str, team_ids: list[int], start: datetime, end: datetime) -> None:
        with self.assertRaises(ValueError):
            preview_rollup(team_ids=team_ids, start=start, end=end)

    def test_other_teams_are_not_rolled_up(self) -> None:
        self._insert_logs([self._log(_START), {**self._log(_START), "team_id": self.team.id + 10_000}])

        self.assertEqual(self._preview().rollup_rows, 1)


def test_mv_matches_the_detector_grid_and_dimension_keys() -> None:
    sql = LOGS34_TO_VOLUME_BUCKETS_MV()

    assert f"toIntervalSecond({BUCKET_SECONDS})" in sql
    assert "lower(severity_text)" in sql
    for chain in (_ENVIRONMENT_KEYS, _NAMESPACE_KEYS):
        first_seen = [sql.index(f"'{key}'") for key in chain]
        assert first_seen == sorted(first_seen)
