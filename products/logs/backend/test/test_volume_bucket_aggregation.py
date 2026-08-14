import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend.temporal.volume_tick.aggregation import aggregate_buckets
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

    def _rollup_rows(self, generation: int) -> list[tuple]:
        return sync_execute(
            """
            SELECT time_bucket, service_name, namespace, environment, severity_text, log_count
            FROM logs_volume_buckets
            WHERE team_id = %(team_id)s AND generation = %(generation)s
            ORDER BY time_bucket, service_name, namespace, environment, severity_text
            """,
            {"team_id": self.team.id, "generation": generation},
        )

    def _aggregate(self, generation: int, *, start: datetime = _START, end: datetime = _END) -> int:
        return aggregate_buckets(team_ids=[self.team.id], start=start, end=end, generation=generation).rows_written

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
        self._aggregate(generation=1)

        rolled_up = [(row[1], row[4], row[5]) for row in self._rollup_rows(generation=1)]
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

    def test_generations_are_disjoint(self) -> None:
        self._insert_logs([self._log(_START)])

        self._aggregate(generation=1)
        self._aggregate(generation=2)

        self.assertEqual(len(self._rollup_rows(generation=1)), 1)
        self.assertEqual(len(self._rollup_rows(generation=2)), 1)
        both = sync_execute(
            "SELECT uniqExact(generation) FROM logs_volume_buckets WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        )
        self.assertEqual(both[0][0], 2)

    def test_logs_land_in_their_own_grid_bucket(self) -> None:
        second_bucket = _START + timedelta(seconds=BUCKET_SECONDS)
        self._insert_logs(
            [
                self._log(second_bucket - timedelta(seconds=1)),
                self._log(second_bucket),
            ]
        )

        self._aggregate(generation=1, start=_START, end=second_bucket + timedelta(seconds=BUCKET_SECONDS))

        # time_bucket is DateTime('UTC'), so the driver hands back aware datetimes.
        buckets = [(row[0], row[5]) for row in self._rollup_rows(generation=1)]
        self.assertEqual(buckets, [(_START, 1), (second_bucket, 1)])
        self.assertEqual([row[0].utcoffset() for row in self._rollup_rows(generation=1)], [timedelta(0)] * 2)

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

        self._aggregate(generation=1)

        self.assertEqual([row[3] for row in self._rollup_rows(generation=1)], [expected])

    @parameterized.expand([("present", {"k8s.namespace.name": "web"}, "web"), ("absent", {}, "")])
    def test_namespace_is_verbatim_with_no_sentinel(
        self, _name: str, resource_attributes: dict[str, str], expected: str
    ) -> None:
        self._insert_logs([self._log(_START, resource_attributes=resource_attributes)])

        self._aggregate(generation=1)

        self.assertEqual([row[2] for row in self._rollup_rows(generation=1)], [expected])

    def test_severity_casing_merges_into_one_series(self) -> None:
        self._insert_logs([self._log(_START, severity="ERROR"), self._log(_START, severity="error")])

        self._aggregate(generation=1)

        rows = self._rollup_rows(generation=1)
        self.assertEqual([(row[4], row[5]) for row in rows], [("error", 2)])

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
            aggregate_buckets(team_ids=team_ids, start=start, end=end, generation=1)

    def test_other_teams_are_not_rolled_up(self) -> None:
        self._insert_logs([self._log(_START), {**self._log(_START), "team_id": self.team.id + 10_000}])

        rows_written = self._aggregate(generation=1)

        self.assertEqual(rows_written, 1)
        self.assertEqual(len(self._rollup_rows(generation=1)), 1)
