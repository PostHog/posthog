from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.runpod import runpod
from products.warehouse_sources.sources.runpod._config import RunPodSourceConfig
from products.warehouse_sources.sources.runpod.runpod import (
    RunPodResumeConfig,
    _normalize_billing_record,
    validate_credentials,
)
from products.warehouse_sources.sources.runpod.source import RunPodSource
from products.warehouse_sources.sources.sdk.testing import DriveResult, ScriptedResponse, SourceDriver, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(RunPodSource(), RunPodSourceConfig(api_key="rpa_test"))


def _collect(
    responses: list[dict], endpoint: str, resume_state: RunPodResumeConfig | None = None, **kw: Any
) -> tuple[DriveResult, list[dict[str, list[str]]]]:
    """Run an extraction against scripted pages; returns the result and the query params of each request."""
    result = _driver().run(
        endpoint, [ScriptedResponse(json=page) for page in responses], resume_state=resume_state, **kw
    )
    return result, [{name: list(values) for name, values in query.items()} for query in result.queries]


class TestNormalizeBillingRecord:
    def test_start_time_is_aliased_to_time(self) -> None:
        # v2 names the bucket start `startTime`, but the schema declares `time` as the incremental
        # field and the partition key, so without this alias `time` never lands in the yielded row.
        record = _normalize_billing_record({"startTime": "2025-08-01T00:00:00Z", "totalAmount": 1.5})
        assert record["time"] == "2025-08-01T00:00:00Z"
        assert "startTime" not in record

    @parameterized.expand(
        [
            (
                "pod",
                {"podId": "pod_abc"},
                "4d2fc9195d93023d7290184fcd9890d06e011005862adaecd693b4faea329303",
            ),
            (
                "serverless",
                {"serverlessId": "ep_abc"},
                "d3f9ef6eae9e450e00fc12d110a9f459c7a3927011ec167fe81d754c1a2b2b25",
            ),
        ]
    )
    def test_v2_record_keeps_the_id_a_v1_sync_wrote(self, _name: str, resource: dict, v1_id: str) -> None:
        # The ids are what v1 syncs wrote for the same bucket and resource. A changed id makes merge
        # insert a second row for every bucket in the lookback window, which double-counts spend.
        record = _normalize_billing_record({"startTime": "2026-11-01T00:00:00Z", **resource, "totalAmount": 1.0})
        assert record["id"] == v1_id


class TestBillingWindows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2022-05-15T12:00:00Z", tick=False):
            yield

    def test_full_refresh_walks_windows_from_launch_date(self) -> None:
        responses = [
            {
                "records": [
                    {"startTime": "2022-02-01T00:00:00Z", "podId": "p1", "totalAmount": 2.0},
                    {"startTime": "2022-01-01T00:00:00Z", "podId": "p1", "totalAmount": 1.0},
                ]
            },
            {"records": [{"startTime": "2022-04-15T00:00:00Z", "podId": "p1", "totalAmount": 3.0}]},
        ]
        result, calls = _collect(responses, "billing_pods")
        rows = result.rows

        # 2022-01-01 + 90 days = 2022-04-01; the second window reaches past "now" so endTime is
        # omitted to include the open bucket, and the walk terminates.
        assert len(calls) == 2
        assert calls[0]["startTime"] == ["2022-01-01T00:00:00Z"]
        assert calls[0]["endTime"] == ["2022-04-01T00:00:00Z"]
        assert calls[1]["startTime"] == ["2022-04-01T00:00:00Z"]
        assert "endTime" not in calls[1]
        assert calls[0]["bucketSize"] == ["day"]

        # Rows within a window are sorted ascending on the bucket start (sort_mode="asc" contract).
        assert [r["time"] for r in rows] == [
            "2022-01-01T00:00:00Z",
            "2022-02-01T00:00:00Z",
            "2022-04-15T00:00:00Z",
        ]
        assert all(r["id"] for r in rows)

        # State is saved after each non-final window so a crash resumes without skipping data.
        assert [s.window_start for s in result.saved_states] == ["2022-04-01T00:00:00Z"]

    def test_resumes_from_saved_window_start(self) -> None:
        _, calls = _collect([{"records": []}], "billing_pods", RunPodResumeConfig(window_start="2022-04-01T00:00:00Z"))
        assert len(calls) == 1
        assert calls[0]["startTime"] == ["2022-04-01T00:00:00Z"]

    def test_a_run_with_no_saved_state_starts_from_the_launch_date(self) -> None:
        _, calls = _collect([{"records": []}], "billing_pods")
        assert calls[0]["startTime"] == ["2022-01-01T00:00:00Z"]

    def test_future_watermark_clamped_to_today(self) -> None:
        # A future-dated watermark must not skip syncing entirely; it re-pulls today's open bucket.
        _, calls = _collect(
            [{"records": []}],
            "billing_pods",
            incremental_field="time",
            db_incremental_field_last_value=datetime(2030, 1, 1, tzinfo=UTC),
        )
        assert len(calls) == 1
        assert calls[0]["startTime"] == ["2022-05-15T00:00:00Z"]

    def test_endpoint_billing_reads_serverless_billing(self) -> None:
        # In v2, `/billing/endpoints` is Public Endpoint billing. Reading it would fill the table
        # with another product's spend and the sync would still succeed.
        result, _ = _collect([{"records": []}], "billing_endpoints")
        assert set(result.paths) == {"/v2/billing/serverless"}

    def test_network_volume_billing_keeps_one_row_per_volume(self) -> None:
        # v2 returns one record per volume per bucket. Without the volume in the id, merge keeps
        # only one volume's charge for each day.
        responses = [
            {
                "records": [
                    {"startTime": "2022-05-15T00:00:00Z", "networkVolumeId": "vol_a", "totalAmount": 1.0},
                    {"startTime": "2022-05-15T00:00:00Z", "networkVolumeId": "vol_b", "totalAmount": 2.0},
                ]
            }
        ]
        result, _ = _collect(
            responses,
            "billing_network_volumes",
            incremental_field="time",
            db_incremental_field_last_value=datetime(2022, 5, 15, tzinfo=UTC),
        )
        assert len({r["id"] for r in result.rows}) == 2


class TestSensitiveDataStripping:
    @parameterized.expand(["pods", "endpoints", "templates"])
    def test_env_secrets_are_stripped_from_inventory_rows(self, endpoint: str) -> None:
        # A user-configured env map or startup command on a Pod/endpoint/template can hold cloud
        # credentials (as env values or CLI args); none of them may reach the warehouse where any
        # project member with warehouse access could read them.
        key = runpod.RUNPOD_ENDPOINTS[endpoint].response_key
        responses = [
            {
                key: [
                    {
                        "id": "r1",
                        "name": "worker",
                        "env": {"AWS_SECRET_ACCESS_KEY": "supersecret"},
                        "args": "serve --api-key=supersecret",
                        "cmd": ["serve", "--api-key=supersecret"],
                        "entrypoint": ["/entry.sh", "--token=supersecret"],
                    },
                    {"id": "r2", "name": "trainer", "env": {}},
                ],
                "pagination": {"nextCursor": None, "hasNextPage": False},
            }
        ]
        result, _ = _collect(responses, endpoint)
        rows = result.rows
        assert [r["id"] for r in rows] == ["r1", "r2"]
        assert all(key not in r for r in rows for key in ("env", "args", "cmd", "entrypoint"))


class TestInventoryPagination:
    def test_follows_next_cursor_until_the_last_page(self) -> None:
        responses = [
            {"pods": [{"id": "p1"}], "pagination": {"nextCursor": "c2", "hasNextPage": True}},
            {"pods": [{"id": "p2"}], "pagination": {"nextCursor": None, "hasNextPage": False}},
        ]
        result, calls = _collect(responses, "pods")
        assert [r["id"] for r in result.rows] == ["p1", "p2"]
        assert [c.get("cursor") for c in calls] == [None, ["c2"]]


class TestSampleCapture:
    @parameterized.expand(
        [
            ("pods", False),
            ("endpoints", False),
            ("templates", False),
            ("network_volumes", True),
            ("billing_pods", True),
        ]
    )
    def test_capture_disabled_only_where_responses_carry_env_secrets(
        self, endpoint: str, expected_capture: bool
    ) -> None:
        # Endpoints whose responses carry user-configured env secrets are excluded from HTTP sample
        # capture — the env values have arbitrary names the name-based scrubbers can't redact — while
        # secret-free endpoints keep capture on for debugging fixtures.
        result, _ = _collect([{runpod.RUNPOD_ENDPOINTS[endpoint].response_key: []}], endpoint)

        assert result.session_options[0].get("capture") is expected_capture


class TestFetchJson:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_exhaust_retry_budget(self, _name: str, status: int) -> None:
        response = MagicMock(status_code=status, ok=False)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(runpod._fetch_json.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(runpod.RunPodRetryableError):
                runpod._fetch_json(session, "https://api.runpod.io/v2/pods", {}, MagicMock())
        assert session.get.call_count == 5

    def test_client_error_raises_for_status_without_retry(self) -> None:
        response = MagicMock(status_code=401, ok=False, text="unauthorized")
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            runpod._fetch_json(session, "https://api.runpod.io/v2/pods", {}, MagicMock())
        assert session.get.call_count == 1

    def test_non_object_response_raises(self) -> None:
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = [{"id": "p1"}]
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(ValueError):
            runpod._fetch_json(session, "https://api.runpod.io/v2/pods", {}, MagicMock())


class TestValidateCredentials:
    @parameterized.expand([("forbidden_scope", 403, True)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (real key restricted to other endpoints); 401 means a bad key.
        with scripted_network([ScriptedResponse(status=status)]):
            assert validate_credentials("rpa_test") is expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.runpod.io/v2/billing/pods", True),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.runpod.io/v2/pods", True),
            ("read_timeout", "HTTPSConnectionPool(host='api.runpod.io', port=443): Read timed out.", False),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.runpod.io/v2/pods", False),
        ]
    )
    def test_only_credential_errors_are_non_retryable(self, _name: str, observed_error: str, expected: bool) -> None:
        non_retryable = RunPodSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected
