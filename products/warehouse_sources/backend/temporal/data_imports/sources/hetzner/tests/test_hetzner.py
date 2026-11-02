import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hetzner import (
    HetznerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import (
    HETZNER_BASE_URL,
    METRICS_RETENTION,
    HetznerResumeConfig,
    hetzner_metrics_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.source import HetznerSource

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _page(
    items: list[dict[str, Any]] | None,
    *,
    endpoint: str = "servers",
    last_page: int = 1,
    status: int = 200,
    drop_key: bool = False,
    reason: str = "",
) -> Response:
    body: dict[str, Any] = {"meta": {"pagination": {"last_page": last_page}}}
    if not drop_key:
        body[endpoint] = items or []
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{HETZNER_BASE_URL}/{endpoint}"
    resp.reason = reason
    return resp


def _make_manager(resume_state: HetznerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _driver() -> SourceDriver:
    return SourceDriver(HetznerSource(), HetznerSourceConfig(api_token="token"))


def _scripted_page(
    items: list[dict[str, Any]] | None,
    *,
    endpoint: str = "servers",
    last_page: int = 1,
    status: int = 200,
) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={endpoint: items or [], "meta": {"pagination": {"last_page": last_page}}},
    )


def _scripted_metrics(time_series: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"metrics": {"start": "", "end": "", "step": 300, "time_series": time_series}})


class TestPagination:
    def test_paginates_until_last_page(self) -> None:
        result = _driver().run(
            "servers",
            [
                _scripted_page([{"id": 1}, {"id": 2}], last_page=2),
                _scripted_page([{"id": 3}], last_page=2),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        # last_page=2 stops after page 2 — no extra empty-page request.
        assert len(result.requests) == 2
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == ["50", "50"]
        # Checkpoint saved after the first page, pointing at the next page.
        assert result.saved_states == [HetznerResumeConfig(page=2)]

    def test_resumes_from_the_saved_page(self) -> None:
        result = _driver().run(
            "servers",
            [_scripted_page([{"id": 3}], last_page=3), _scripted_page([{"id": 4}], last_page=3)],
            resume_state=HetznerResumeConfig(page=2),
        )

        assert result.raised is None
        assert result.params("page") == ["2", "3"]
        assert [row["id"] for row in result.rows] == [3, 4]


NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _json_response(body: dict[str, Any], *, status: int = 200, reason: str = "") -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = HETZNER_BASE_URL
    resp.reason = reason
    return resp


def _metrics(time_series: dict[str, Any]) -> Response:
    return _json_response({"metrics": {"start": "", "end": "", "step": 300, "time_series": time_series}})


def _wire_requests(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    session.headers = {}
    sent: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        sent.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return sent


def _rfc3339(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _metrics_source(endpoint: str, manager: mock.MagicMock, last_value: Any = None):
    return hetzner_metrics_source(
        api_token="token",
        endpoint=endpoint,
        resumable_source_manager=manager,
        db_incremental_field_last_value=last_value,
    )


class TestMetrics:
    @pytest.fixture(autouse=True)
    def _frozen_now(self):
        with time_machine.travel(NOW, tick=False):
            yield

    @parameterized.expand(
        [
            ("server_metrics", "servers", "server_id", "cpu,disk,network"),
            (
                "load_balancer_metrics",
                "load_balancers",
                "load_balancer_id",
                "open_connections,connections_per_second,requests_per_second,bandwidth",
            ),
        ]
    )
    def test_flattens_series_into_one_row_per_sample(
        self, endpoint: str, parent: str, id_column: str, types: str
    ) -> None:
        created = NOW - timedelta(minutes=58)
        sample = (NOW - timedelta(minutes=5)).timestamp()
        result = _driver().run(
            endpoint,
            [
                _scripted_page([{"id": 7, "created": created.isoformat()}], endpoint=parent),
                _scripted_metrics(
                    {"a": {"values": [[sample, "12.5"]]}, "b": {"values": [[sample, "3"], [sample + 300, "NaN"]]}}
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {id_column: 7, "metric": "a", "timestamp": NOW - timedelta(minutes=5), "value": 12.5},
            {id_column: 7, "metric": "b", "timestamp": NOW - timedelta(minutes=5), "value": 3.0},
            {id_column: 7, "metric": "b", "timestamp": NOW, "value": None},
        ]
        request = result.requests[1]
        assert request.url.startswith(f"{HETZNER_BASE_URL}/{parent}/7/metrics?")
        # A start before the resource existed would only fetch empty windows; it rounds up to the grid.
        assert request.query == {
            "type": (types,),
            "start": (_rfc3339(NOW - timedelta(minutes=55)),),
            "end": (_rfc3339(NOW),),
            "step": ("300",),
        }

    @parameterized.expand([("incremental", True, 20), ("full_refresh", False, 55)])
    def test_an_incremental_run_starts_from_the_watermark(
        self, _name: str, should_use_incremental_field: bool, minutes_back: int
    ) -> None:
        created = NOW - timedelta(minutes=58)
        result = _driver().run(
            "server_metrics",
            [_scripted_page([{"id": 7, "created": created.isoformat()}]), _scripted_metrics({})],
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="timestamp",
            db_incremental_field_last_value=NOW - timedelta(minutes=20),
        )

        assert result.raised is None
        assert result.requests[1].param("start") == _rfc3339(NOW - timedelta(minutes=minutes_back))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_walks_retention_in_contiguous_windows(self, MockSession) -> None:
        session = MockSession.return_value
        window_count = 18  # 8629 five-minute samples in the retention span, 500 per request
        sent = _wire_requests(
            session,
            [_page([{"id": 1, "created": "2020-01-01T00:00:00+00:00"}])] + [_metrics({}) for _ in range(window_count)],
        )
        manager = _make_manager()

        rows = _rows(_metrics_source("server_metrics", manager))

        assert rows == []
        windows = [params for _, params in sent[1:]]
        assert len(windows) == window_count
        assert windows[0]["start"] == _rfc3339(NOW - METRICS_RETENTION)
        assert windows[-1]["end"] == _rfc3339(NOW)
        for previous, following in zip(windows, windows[1:]):
            gap = datetime.fromisoformat(following["start"]) - datetime.fromisoformat(previous["end"])
            assert gap == timedelta(seconds=300)
        # Empty windows still give the pipeline a chance to hand the run off during a shutdown.
        assert manager.safe_point.call_count == window_count

    def test_resource_deleted_mid_sync_is_skipped(self) -> None:
        recent = (NOW - timedelta(minutes=30)).isoformat()
        sample = NOW.timestamp()
        result = _driver().run(
            "server_metrics",
            [
                _scripted_page([{"id": 1, "created": recent}, {"id": 2, "created": recent}]),
                ScriptedResponse(status=404, json={"error": {"code": "not_found"}}),
                _scripted_metrics({"cpu": {"values": [[sample, "1"]]}}),
            ],
        )

        assert result.raised is None
        assert [(row["server_id"], row["value"]) for row in result.rows] == [(2, 1.0)]
        assert result.paths == ["/v1/servers", "/v1/servers/1/metrics", "/v1/servers/2/metrics"]


class TestChildEndpoints:
    @parameterized.expand(
        [
            (
                "network_members",
                "networks",
                "members",
                {"type": "server", "id": 9, "ip": "10.0.0.2"},
                {"network_id": 3, "type": "server", "id": 9, "ip": "10.0.0.2"},
            ),
            (
                "zone_rrsets",
                "zones",
                "rrsets",
                {"id": "www/A", "name": "www", "type": "A", "zone": 3, "records": [{"value": "198.51.100.7"}]},
                {"zone": 3, "id": "www/A", "name": "www", "type": "A", "records": [{"value": "198.51.100.7"}]},
            ),
        ]
    )
    def test_fans_out_over_parents_and_skips_deleted_or_empty_ones(
        self,
        endpoint: str,
        parent: str,
        child_key: str,
        child_row: dict[str, Any],
        expected_row: dict[str, Any],
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _scripted_page([{"id": 1}, {"id": 2}, {"id": 3}], endpoint=parent),
                ScriptedResponse(status=404, json={"error": {"code": "not_found"}}),
                _scripted_page([], endpoint=child_key),
                _scripted_page([child_row], endpoint=child_key),
            ],
        )

        assert result.raised is None
        assert result.rows == [expected_row]
        assert result.paths == [
            f"/v1/{parent}",
            f"/v1/{parent}/1/{child_key}",
            f"/v1/{parent}/2/{child_key}",
            f"/v1/{parent}/3/{child_key}",
        ]
        assert result.params("sort") == ["id:asc"] * 4


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_status_is_retried_then_reraised(self, _name: str, status: int) -> None:
        result = _driver().run("servers", always(_scripted_page([], status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1
        assert set(result.paths) == {"/v1/servers"}

    def test_client_error_is_not_retried(self) -> None:
        # A 401 is fatal; raising HTTPError immediately (not retrying) lets get_non_retryable_errors act.
        result = _driver().run("servers", [_scripted_page([], status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
        ]
    )
    def test_status_maps_to_validity(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            valid, message = validate_credentials("token")
        assert valid is expected_valid
        assert message == expected_message
        assert network.requests_log[0].path == "/v1/ssh_keys"
        assert network.requests_log[0].param("per_page") == "1"

    def test_network_error_is_invalid_not_raised(self) -> None:
        # A probe transport failure must return "not validated", never raise out of source creation.
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            valid, message = validate_credentials("token")
        assert valid is False
        assert message == "Could not reach the Hetzner Cloud API"
        assert {request.path for request in network.requests_log} == {"/v1/ssh_keys"}


class TestSourceResponse:
    @parameterized.expand([("actions",), ("server_types",), ("locations",)])
    def test_no_partition_for_timestampless_endpoints(self, endpoint: str) -> None:
        # actions has no `created`; catalog endpoints carry no timestamps — partitioning on a null or
        # absent field would rewrite partitions every sync, so these must stay unpartitioned.
        result = _driver().run(endpoint, [_scripted_page([], endpoint=endpoint)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_mode is None
        assert response.partition_keys is None
