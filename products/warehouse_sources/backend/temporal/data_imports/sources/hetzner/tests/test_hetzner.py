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
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import (
    HETZNER_BASE_URL,
    METRICS_RETENTION,
    HetznerResumeConfig,
    hetzner_child_source,
    hetzner_metrics_source,
    hetzner_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hetzner module.
HETZNER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner.make_tracked_session"
)
# Retryable tests: silence tenacity's backoff so retries don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


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


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return hetzner_source(
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": 1}, {"id": 2}], last_page=2),
                _page([{"id": 3}], last_page=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("servers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        # last_page=2 stops after page 2 — no extra empty-page request.
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 50
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page, pointing at the next page.
        manager.save_state.assert_called_once_with(HetznerResumeConfig(page=2))


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_series_into_one_row_per_sample(
        self, endpoint: str, parent: str, id_column: str, types: str, MockSession
    ) -> None:
        session = MockSession.return_value
        created = NOW - timedelta(minutes=58)
        sample = (NOW - timedelta(minutes=5)).timestamp()
        sent = _wire_requests(
            session,
            [
                _page([{"id": 7, "created": created.isoformat()}], endpoint=parent),
                _metrics(
                    {"a": {"values": [[sample, "12.5"]]}, "b": {"values": [[sample, "3"], [sample + 300, "NaN"]]}}
                ),
            ],
        )

        rows = _rows(_metrics_source(endpoint, _make_manager()))

        assert rows == [
            {id_column: 7, "metric": "a", "timestamp": NOW - timedelta(minutes=5), "value": 12.5},
            {id_column: 7, "metric": "b", "timestamp": NOW - timedelta(minutes=5), "value": 3.0},
            {id_column: 7, "metric": "b", "timestamp": NOW, "value": None},
        ]
        url, params = sent[1]
        assert url == f"{HETZNER_BASE_URL}/{parent}/7/metrics"
        # A start before the resource existed would only fetch empty windows; it rounds up to the grid.
        assert params == {
            "type": types,
            "start": _rfc3339(NOW - timedelta(minutes=55)),
            "end": _rfc3339(NOW),
            "step": 300,
        }

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resource_deleted_mid_sync_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        recent = (NOW - timedelta(minutes=30)).isoformat()
        sample = NOW.timestamp()
        _wire_requests(
            session,
            [
                _page([{"id": 1, "created": recent}, {"id": 2, "created": recent}]),
                _json_response({"error": {"code": "not_found"}}, status=404, reason="Not Found"),
                _metrics({"cpu": {"values": [[sample, "1"]]}}),
            ],
        )

        rows = _rows(_metrics_source("server_metrics", _make_manager()))

        assert [(r["server_id"], r["value"]) for r in rows] == [(2, 1.0)]


class TestNetworkMembers:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_or_empty_network_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_requests(
            session,
            [
                _page([{"id": 1}, {"id": 2}, {"id": 3}], endpoint="networks"),
                _json_response({"error": {"code": "not_found"}}, status=404, reason="Not Found"),
                _page([], endpoint="members"),
                _page([{"type": "server", "id": 9}], endpoint="members"),
            ],
        )
        manager = _make_manager()

        rows = _rows(
            hetzner_child_source(api_token="token", endpoint="network_members", resumable_source_manager=manager)
        )

        assert rows == [{"network_id": 3, "type": "server", "id": 9}]
        assert manager.safe_point.call_count == 2


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(SLEEP_PATCH, lambda *_: None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_status_is_retried_then_reraised(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], status=status, reason="err") for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("servers", _make_manager()))
        # 5 attempts (DEFAULT_RETRY_ATTEMPTS) before giving up.
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_is_not_retried(self, MockSession) -> None:
        # A 401 is fatal; raising HTTPError immediately (not retrying) lets get_non_retryable_errors act.
        session = MockSession.return_value
        _wire(session, [_page([], status=401, reason="Unauthorized")])

        with pytest.raises(requests.HTTPError):
            _rows(_source("servers", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("unauthorized", 401, False, "Invalid Hetzner Cloud API token"),
            ("forbidden", 403, False, "Invalid Hetzner Cloud API token"),
        ]
    )
    @mock.patch(HETZNER_SESSION_PATCH)
    def test_status_maps_to_validity(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        valid, message = validate_credentials("token")
        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(HETZNER_SESSION_PATCH)
    def test_network_error_is_invalid_not_raised(self, mock_session) -> None:
        # A probe transport failure must return "not validated", never raise out of source creation.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, message = validate_credentials("token")
        assert valid is False
        assert message == "Could not reach the Hetzner Cloud API"


class TestSourceResponse:
    @parameterized.expand([("actions",), ("server_types",), ("locations",)])
    def test_no_partition_for_timestampless_endpoints(self, endpoint: str) -> None:
        # actions has no `created`; catalog endpoints carry no timestamps — partitioning on a null or
        # absent field would rewrite partitions every sync, so these must stay unpartitioned.
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source(endpoint, _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
