import json
import base64
import datetime as dt
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.logs.backend.context_query_runner import (
    BODY_MAX_CHARS,
    LogsContextRunner,
    differing_attrs,
    is_id_like_key,
    parse_padding,
    self_time_nano,
)

_NOW = "2026-06-23T13:00:00Z"
_TRACE_HEX = "4bf92f3577b34da6a3ce929d0e0e4736"
_OTHER_TRACE_HEX = "00f067aa0ba902b7a3ce929d0e0e4736"


def _b64_hex(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode()


def _ts(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


_T0 = dt.datetime(2026, 6, 23, 12, 0, 0)


class TestContextHelpers(TestCase):
    @parameterized.expand(
        [
            ("seconds", "30s", dt.timedelta(seconds=30)),
            ("minutes", "5m", dt.timedelta(minutes=5)),
            ("hours", "1h", dt.timedelta(hours=1)),
        ]
    )
    def test_parse_padding(self, _name: str, raw: str, expected: dt.timedelta) -> None:
        assert parse_padding(raw) == expected

    @parameterized.expand(
        [("no_unit", "30"), ("bad_unit", "5d"), ("too_long", "7h"), ("empty", ""), ("huge", "9999999999999999999s")]
    )
    def test_parse_padding_rejects(self, _name: str, raw: str) -> None:
        with self.assertRaises(ValueError):
            parse_padding(raw)

    def test_self_time_subtracts_the_union_of_child_intervals(self) -> None:
        start = dt.datetime(2026, 6, 23, 12, 0, tzinfo=dt.UTC)
        children = [
            (start + dt.timedelta(seconds=1), start + dt.timedelta(seconds=7)),
            (start + dt.timedelta(seconds=3), start + dt.timedelta(seconds=8)),
            (start + dt.timedelta(seconds=9), start + dt.timedelta(seconds=12)),
        ]

        assert self_time_nano(start, start + dt.timedelta(seconds=10), 10_000_000_000, children) == 2_000_000_000

    @parameterized.expand(
        [
            ("trace_id", "trace_id", True),
            ("suffix_id", "workflow_run_id", True),
            ("dotted_id", "http.request.id", True),
            ("run_prefix", "run_name", True),
            ("request_prefix", "request_path", True),
            ("camel_id", "jobId", True),
            ("plain", "status", False),
            ("contains_id_inside", "idle_ms", False),
        ]
    )
    def test_is_id_like_key(self, _name: str, key: str, expected: bool) -> None:
        assert is_id_like_key(key) is expected

    def test_differing_attrs_drops_noise_and_values_equal_to_the_anchor(self) -> None:
        anchor = {"request_id": "r-1", "region": "eu", "time": "a"}
        row = {
            "request_id": "r-1",
            "region": "us",
            "status": "500",
            "time": "b",
            "log.file.path": "/var/log/x.log",
            "code.lineno": "42",
        }
        assert differing_attrs(row, anchor) == "region=us status=500"


class TestLogsContextAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _insert_logs(self, rows: list[dict]) -> None:
        sql = "".join(json.dumps({"team_id": self.team.id, **r}) + "\n" for r in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{sql}")

    def _log(
        self,
        uuid: str,
        at: dt.datetime,
        body: str,
        *,
        service: str = "api",
        severity: str = "info",
        trace_hex: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> dict:
        return {
            "uuid": uuid,
            "timestamp": _ts(at),
            "observed_timestamp": _ts(at),
            "body": body,
            "severity_text": severity,
            "service_name": service,
            "trace_id": _b64_hex(trace_hex) if trace_hex else "",
            "span_id": "",
            "attributes_map_str": {f"{key}__str": value for key, value in (attributes or {}).items()},
        }

    def _insert_spans(self, spans: list[tuple]) -> None:
        rows = []
        for index, (span_hex, parent_hex, name, service, start, end, status_code) in enumerate(spans):
            rows.append(
                f"('019e8754-0000-0000-0000-{index:012d}', {self.team.id}, '{_b64_hex(_TRACE_HEX)}', "
                f"'{_b64_hex(span_hex)}', '{_b64_hex(parent_hex) if parent_hex else ''}', '{name}', 2, "
                f"'{_ts(start)}', '{_ts(end)}', '{_ts(start)}', {status_code}, '{service}')"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name) VALUES " + ",".join(rows)
        )

    def _seed_trace(self) -> None:
        self._insert_spans(
            [
                ("1000000000000001", None, "POST /jobs", "api", _T0, _T0 + dt.timedelta(seconds=2), 0),
                (
                    "1000000000000002",
                    "1000000000000001",
                    "run job",
                    "worker",
                    _T0 + dt.timedelta(milliseconds=100),
                    _T0 + dt.timedelta(milliseconds=1900),
                    2,
                ),
                (
                    "1000000000000003",
                    "1000000000000002",
                    "SELECT jobs",
                    "worker",
                    _T0 + dt.timedelta(milliseconds=200),
                    _T0 + dt.timedelta(milliseconds=500),
                    0,
                ),
            ]
        )

    def _request(self, query: dict, expected_status: int = status.HTTP_200_OK) -> dict:
        response = self.client.post(f"/api/projects/{self.team.id}/logs/context/", {"query": query}, format="json")
        self.assertEqual(response.status_code, expected_status, response.content)
        return response.json()

    @time_machine.travel(_NOW, tick=False)
    def test_trace_anchor_bounds_the_logs_query_by_the_trace_spans(self) -> None:
        self._seed_trace()
        self._insert_logs(
            [
                self._log(
                    "00000000-0000-0000-0000-000000000001",
                    _T0 + dt.timedelta(seconds=1),
                    "job accepted",
                    trace_hex=_TRACE_HEX,
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000002",
                    _T0 + dt.timedelta(milliseconds=1500),
                    "job failed: timeout",
                    service="worker",
                    severity="error",
                    trace_hex=_TRACE_HEX,
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000003",
                    _T0 + dt.timedelta(minutes=5),
                    "late retry",
                    trace_hex=_TRACE_HEX,
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000004",
                    _T0 + dt.timedelta(seconds=1),
                    "sidecar line",
                    service="sidecar",
                    trace_hex=_TRACE_HEX,
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000005",
                    _T0 + dt.timedelta(seconds=1),
                    "unrelated",
                    trace_hex=_OTHER_TRACE_HEX,
                ),
            ]
        )

        body = self._request({"anchor": {"traceId": _TRACE_HEX}})

        assert body["window"] == {
            "current": {"from": "2026-06-23T11:59:30Z", "to": "2026-06-23T12:00:32Z"},
            "timezone": "UTC",
        }
        assert body["anchor"]["type"] == "trace"
        assert body["anchor"]["trace_id"] == _TRACE_HEX
        assert body["anchor"]["start"] == "2026-06-23T12:00:00Z"
        assert body["anchor"]["end"] == "2026-06-23T12:00:02Z"
        assert body["anchor"]["duration_ms"] == 2000.0
        assert body["anchor"]["services"] == ["api", "worker"]
        assert [row["body"] for row in body["timeline"]] == ["job accepted", "job failed: timeout"]
        assert [row["t_offset_ms"] for row in body["timeline"]] == [1000.0, 1500.0]
        assert [row["service"] for row in body["timeline"]] == ["api", "worker"]
        assert body["timeline"][1]["severity"] == "error"
        assert body["truncated"] is False
        assert body["next_cursor"] is None
        assert body["spans_summary"] is None

    @time_machine.travel(_NOW, tick=False)
    def test_trace_anchor_with_spans_include_summarizes_the_trace(self) -> None:
        self._seed_trace()

        body = self._request({"anchor": {"traceId": _TRACE_HEX}, "include": ["spans"]})

        summary = body["spans_summary"]
        assert summary["span_count"] == 3
        assert summary["services"] == ["api", "worker"]
        assert summary["root"] == {
            "span_id": "1000000000000001",
            "name": "POST /jobs",
            "service": "api",
            "start_offset_ms": 0.0,
            "duration_ms": 2000.0,
            "self_time_ms": 200.0,
            "status": "ok",
        }
        assert [span["name"] for span in summary["error_spans"]] == ["run job"]
        assert [span["name"] for span in summary["slowest"]] == ["POST /jobs", "run job", "SELECT jobs"]
        assert summary["slowest"][1]["self_time_ms"] == 1500.0
        assert summary["truncated"] is False

    def _request_with_key(self, query: dict, scopes: list[str]) -> Any:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="logs-only", user=self.user, secure_value=hash_key_value(key_value), scopes=scopes
        )
        return self.client.post(
            f"/api/projects/{self.team.id}/logs/context/",
            {"query": query},
            format="json",
            headers={"authorization": f"Bearer {key_value}"},
        )

    @time_machine.travel(_NOW, tick=False)
    def test_spans_need_the_tracing_scope(self) -> None:
        self._seed_trace()

        spans = self._request_with_key({"anchor": {"traceId": _TRACE_HEX}, "include": ["spans"]}, ["logs:read"])
        bounds = self._request_with_key({"anchor": {"traceId": _TRACE_HEX}}, ["logs:read"])

        wildcard = self._request_with_key({"anchor": {"traceId": _TRACE_HEX}, "include": ["spans"]}, ["*"])

        assert spans.status_code == status.HTTP_403_FORBIDDEN, spans.content
        assert wildcard.status_code == status.HTTP_200_OK, wildcard.content
        assert bounds.status_code == status.HTTP_400_BAD_REQUEST, bounds.content
        assert "anchor.around" in json.dumps(bounds.json())

    @time_machine.travel(_NOW, tick=False)
    def test_spans_need_tracing_viewer_access(self) -> None:
        self._seed_trace()

        with patch(
            "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, required_level: resource != "tracing",
        ):
            self._request(
                {"anchor": {"traceId": _TRACE_HEX}, "include": ["spans"]}, expected_status=status.HTTP_403_FORBIDDEN
            )

    @time_machine.travel(_NOW, tick=False)
    def test_zero_padding_keeps_the_trace_bounds(self) -> None:
        self._seed_trace()

        body = self._request({"anchor": {"traceId": _TRACE_HEX}, "padding": "0s"})

        assert body["window"]["current"] == {"from": "2026-06-23T12:00:00Z", "to": "2026-06-23T12:00:02Z"}

    @time_machine.travel(_NOW, tick=False)
    def test_correlation_budget_errors_keep_the_timeline(self) -> None:
        self._insert_logs(
            [self._log("00000000-0000-0000-0000-000000000001", _T0, "hello", attributes={"run_id": "r1"})]
        )

        original = LogsContextRunner._execute

        def fail_correlation(runner: LogsContextRunner, sql: str, placeholders: dict) -> list:
            if "countIf" in sql:
                raise CHQueryErrorTooManyBytes("too many")
            return original(runner, sql, placeholders)

        anchor = {"logUuid": "00000000-0000-0000-0000-000000000001", "timestamp": "2026-06-23T12:00:00Z"}
        with patch.object(LogsContextRunner, "_execute", fail_correlation):
            body = self._request({"anchor": anchor})

        assert [row["body"] for row in body["timeline"]] == ["hello"]
        assert body["correlation_keys"] == []

    @time_machine.travel(_NOW, tick=False)
    def test_trace_anchor_without_spans_needs_a_time_hint(self) -> None:
        response = self._request({"anchor": {"traceId": _TRACE_HEX}}, expected_status=status.HTTP_400_BAD_REQUEST)
        assert "anchor.around" in json.dumps(response)

    @time_machine.travel(_NOW, tick=False)
    def test_trace_anchor_without_spans_uses_around(self) -> None:
        self._insert_logs(
            [
                self._log("00000000-0000-0000-0000-000000000001", _T0, "logs-only trace line", trace_hex=_TRACE_HEX),
                self._log(
                    "00000000-0000-0000-0000-000000000002",
                    _T0 + dt.timedelta(minutes=2),
                    "outside",
                    trace_hex=_TRACE_HEX,
                ),
            ]
        )

        body = self._request({"anchor": {"traceId": _TRACE_HEX, "around": "2026-06-23T12:00:10Z"}})

        assert body["window"]["current"] == {"from": "2026-06-23T11:59:40Z", "to": "2026-06-23T12:00:40Z"}
        assert [row["body"] for row in body["timeline"]] == ["logs-only trace line"]
        assert body["notes"]

    @time_machine.travel(_NOW, tick=False)
    def test_log_anchor_needs_a_timestamp(self) -> None:
        response = self._request(
            {"anchor": {"logUuid": "00000000-0000-0000-0000-000000000001"}}, expected_status=status.HTTP_400_BAD_REQUEST
        )
        assert "anchor.timestamp" in json.dumps(response)

    @time_machine.travel(_NOW, tick=False)
    def test_log_anchor_returns_neighbouring_lines_of_the_same_service(self) -> None:
        anchor_attrs = {"request_id": "req-7", "region": "eu", "log.file.path": "/var/log/api.log"}
        self._insert_logs(
            [
                self._log(
                    "00000000-0000-0000-0000-000000000001",
                    _T0 - dt.timedelta(minutes=1),
                    "before",
                    attributes={"request_id": "req-6", "region": "eu", "log.file.path": "/var/log/api.log"},
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000002",
                    _T0,
                    "anchor line",
                    severity="error",
                    trace_hex=_TRACE_HEX,
                    attributes=anchor_attrs,
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000003",
                    _T0 + dt.timedelta(minutes=2),
                    "after",
                    attributes={"request_id": "req-7", "region": "eu"},
                ),
                self._log("00000000-0000-0000-0000-000000000004", _T0 + dt.timedelta(minutes=10), "far after"),
                self._log("00000000-0000-0000-0000-000000000005", _T0, "other service", service="worker"),
            ]
        )

        body = self._request(
            {"anchor": {"logUuid": "00000000-0000-0000-0000-000000000002", "timestamp": "2026-06-23T12:00:00Z"}}
        )

        assert body["window"]["current"] == {"from": "2026-06-23T11:55:00Z", "to": "2026-06-23T12:05:00Z"}
        assert body["anchor"]["type"] == "log"
        assert body["anchor"]["services"] == ["api"]
        assert body["anchor"]["trace_id"] == _TRACE_HEX
        assert body["timeline"][1]["severity"] == "error"
        assert [row["body"] for row in body["timeline"]] == ["before", "anchor line", "after"]
        assert [row["t_offset_ms"] for row in body["timeline"]] == [-60000.0, 0.0, 120000.0]
        assert body["timeline"][0]["attrs"] == "request_id=req-6"
        assert body["timeline"][1]["attrs"] == ""
        assert body["timeline"][2]["attrs"] == ""
        keys = {(key["key"], key["value"]): key["log_count"] for key in body["correlation_keys"]}
        assert keys == {("trace_id", _TRACE_HEX): 1, ("request_id", "req-7"): 2}
        assert any(suggestion["tool"] == "logs-context" for suggestion in body["next"])

    @time_machine.travel(_NOW, tick=False)
    def test_unknown_log_anchor_is_not_found(self) -> None:
        self._request(
            {"anchor": {"logUuid": "00000000-0000-0000-0000-00000000ffff", "timestamp": "2026-06-23T12:00:00Z"}},
            expected_status=status.HTTP_404_NOT_FOUND,
        )

    @time_machine.travel(_NOW, tick=False)
    def test_attribute_anchor_needs_around(self) -> None:
        response = self._request(
            {"anchor": {"attribute": {"key": "workflow_run_id", "value": "run-42"}}},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        assert "anchor.around" in json.dumps(response)

    @time_machine.travel(_NOW, tick=False)
    def test_attribute_anchor_follows_the_run_across_services(self) -> None:
        run = {"workflow_run_id": "run-42"}
        self._insert_logs(
            [
                self._log(
                    "00000000-0000-0000-0000-000000000001", _T0, "run started", service="scheduler", attributes=run
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000002",
                    _T0 + dt.timedelta(seconds=30),
                    "step failed",
                    service="worker",
                    severity="error",
                    attributes={**run, "step": "upload"},
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000003",
                    _T0 + dt.timedelta(seconds=40),
                    "other run",
                    attributes={"workflow_run_id": "run-43"},
                ),
                self._log(
                    "00000000-0000-0000-0000-000000000004",
                    _T0 + dt.timedelta(hours=1),
                    "same run much later",
                    attributes=run,
                ),
            ]
        )

        body = self._request(
            {"anchor": {"attribute": {"key": "workflow_run_id", "value": "run-42"}, "around": "2026-06-23T12:01:00Z"}}
        )

        assert body["anchor"]["type"] == "attribute"
        assert body["anchor"]["services"] == ["scheduler", "worker"]
        assert body["anchor"]["start"] == "2026-06-23T12:00:00Z"
        assert body["anchor"]["end"] == "2026-06-23T12:00:30Z"
        assert [row["body"] for row in body["timeline"]] == ["run started", "step failed"]
        assert body["timeline"][1]["attrs"] == "step=upload"
        assert {"key": "workflow_run_id", "value": "run-42", "log_count": 2} in body["correlation_keys"]

    @time_machine.travel(_NOW, tick=False)
    def test_severity_levels_filter_the_timeline(self) -> None:
        run = {"workflow_run_id": "run-42"}
        self._insert_logs(
            [
                self._log("00000000-0000-0000-0000-000000000001", _T0, "run started", attributes=run),
                self._log("00000000-0000-0000-0000-000000000002", _T0, "step failed", severity="error", attributes=run),
            ]
        )

        body = self._request(
            {
                "anchor": {
                    "attribute": {"key": "workflow_run_id", "value": "run-42"},
                    "around": "2026-06-23T12:00:00Z",
                },
                "severityLevels": ["error"],
            }
        )

        assert [row["body"] for row in body["timeline"]] == ["step failed"]

    @time_machine.travel(_NOW, tick=False)
    def test_truncated_timeline_returns_a_cursor_for_the_rest(self) -> None:
        run = {"workflow_run_id": "run-42"}
        self._insert_logs(
            [
                self._log(
                    f"00000000-0000-0000-0000-00000000000{index}",
                    _T0 + dt.timedelta(seconds=index),
                    f"line {index}",
                    attributes=run,
                )
                for index in range(1, 4)
            ]
        )
        query = {
            "anchor": {"attribute": {"key": "workflow_run_id", "value": "run-42"}, "around": "2026-06-23T12:00:00Z"},
            "limit": 2,
        }

        first = self._request(query)
        second = self._request({**query, "after": first["next_cursor"]})

        assert [row["body"] for row in first["timeline"]] == ["line 1", "line 2"]
        assert first["truncated"] is True
        assert first["next_cursor"]
        assert any(suggestion["query"].get("after") == first["next_cursor"] for suggestion in first["next"])
        assert [row["body"] for row in second["timeline"]] == ["line 3"]
        assert second["truncated"] is False

    @time_machine.travel(_NOW, tick=False)
    def test_long_bodies_are_truncated(self) -> None:
        self._insert_logs(
            [
                self._log(
                    "00000000-0000-0000-0000-000000000001", _T0, "x" * 1000, attributes={"workflow_run_id": "run-42"}
                )
            ]
        )

        body = self._request(
            {"anchor": {"attribute": {"key": "workflow_run_id", "value": "run-42"}, "around": "2026-06-23T12:00:00Z"}}
        )

        assert len(body["timeline"][0]["body"]) <= BODY_MAX_CHARS + 1
        assert body["timeline"][0]["body"].endswith("…")

    @parameterized.expand(
        [
            ("no_anchor", {"anchor": {}}),
            ("two_anchors", {"anchor": {"traceId": _TRACE_HEX, "logUuid": "u", "timestamp": "2026-06-23T12:00:00Z"}}),
            ("limit_over_cap", {"anchor": {"traceId": _TRACE_HEX, "around": "2026-06-23T12:00:00Z"}, "limit": 501}),
            ("bad_padding", {"anchor": {"traceId": _TRACE_HEX, "around": "2026-06-23T12:00:00Z"}, "padding": "2d"}),
            ("bad_trace_id", {"anchor": {"traceId": "not a trace id!", "around": "2026-06-23T12:00:00Z"}}),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_invalid_requests_are_rejected(self, _name: str, query: dict) -> None:
        self._request(query, expected_status=status.HTTP_400_BAD_REQUEST)
