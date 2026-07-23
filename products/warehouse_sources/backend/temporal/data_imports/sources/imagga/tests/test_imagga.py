import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga import (
    BASE_URL,
    _daily_usage_rows,
    _usage_snapshot_row,
    imagga_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import IMAGGA_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the imagga module.
IMAGGA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga.make_tracked_session"
)

# A representative /usage result, shaped after Imagga's public docs example.
_USAGE_RESULT = {
    "billing_period_start": "18 of Oct, 2018",
    "billing_period_end": "18 of Nov, 2018",
    "monthly_limit": 2000,
    "daily_for": "23 of Oct, 2018",
    "daily_processed": 3,
    "daily_requests": 3,
    "last_usage": 1540300613,
    "concurrency": {"max": 2, "now": 1},
    "daily": {"1519603200": 1, "1540252800": 3},
    "monthly": {"2018-10": 30},
}


def _response(payload: Any, *, status: int = 200, retry_after: Any = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(payload).encode()
    resp.url = f"{BASE_URL}/usage?concurrency=1"
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return resp


def _usage_body(result: Any) -> dict[str, Any]:
    return {"result": result, "status": {"type": "success"}}


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params/auth/url at prepare time.

    ``request.params`` is mutated in place across pages, so a copy is snapshotted per prepared request.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"params": dict(request.params or {}), "auth": request.auth, "url": request.url})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, result: Any, MockSession: mock.MagicMock) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session = MockSession.return_value
    snapshots = _wire(session, [_response(_usage_body(result))])
    rows = _rows(imagga_source("key", "secret", endpoint, team_id=1, job_id="j"))
    return rows, snapshots


class TestUsageSnapshotRow:
    def test_flattens_concurrency_and_excludes_histograms(self) -> None:
        row = _usage_snapshot_row(_USAGE_RESULT)
        # Nested concurrency scalars are flattened with a prefix.
        assert row["concurrency_max"] == 2
        assert row["concurrency_now"] == 1
        # Scalars are carried through unchanged.
        assert row["billing_period_start"] == "18 of Oct, 2018"
        assert row["monthly_limit"] == 2000
        # The period-keyed histograms must stay out of the flat row, or the column set drifts each sync.
        assert "daily" not in row
        assert "monthly" not in row

    def test_empty_result_yields_empty_row(self) -> None:
        assert _usage_snapshot_row({}) == {}


class TestDailyUsageRows:
    def test_explodes_histogram_to_sorted_dated_rows(self) -> None:
        rows = _daily_usage_rows(_USAGE_RESULT)
        # Unix-second keys become calendar days, ascending to keep sort_mode="asc" honest.
        assert rows == [
            {"date": "2018-02-26", "timestamp": 1519603200, "count": 1},
            {"date": "2018-10-23", "timestamp": 1540252800, "count": 3},
        ]

    @parameterized.expand([("missing", {}), ("wrong_type", {"daily": []}), ("null", {"daily": None})])
    def test_returns_empty_when_no_daily_histogram(self, _name: str, result: dict[str, Any]) -> None:
        assert _daily_usage_rows(result) == []

    def test_skips_unparseable_timestamp_keys(self) -> None:
        rows = _daily_usage_rows({"daily": {"not-a-timestamp": 5, "1519603200": 1}})
        assert [r["timestamp"] for r in rows] == [1519603200]


class TestUsageEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_single_snapshot_row(self, MockSession) -> None:
        rows, _ = _run("usage", _USAGE_RESULT, MockSession)
        assert len(rows) == 1
        assert rows[0]["billing_period_start"] == "18 of Oct, 2018"
        assert rows[0]["concurrency_max"] == 2
        assert "daily" not in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_concurrency_param_basic_auth_and_usage_path(self, MockSession) -> None:
        _, snapshots = _run("usage", _USAGE_RESULT, MockSession)
        # Credentials ride in the Basic-auth header (redacted from errors), never the URL.
        assert snapshots[0]["params"] == {"concurrency": "1"}
        assert snapshots[0]["auth"].username == "key"
        assert snapshots[0]["auth"].password == "secret"
        assert snapshots[0]["url"].endswith("/usage")
        assert "concurrency" not in snapshots[0]["url"]

    @parameterized.expand([("null_result", None), ("empty_result", {})])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_result_yields_nothing(self, _name: str, result: Any, MockSession) -> None:
        rows, _ = _run("usage", result, MockSession)
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_key_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"status": {"type": "success"}})])
        assert _rows(imagga_source("key", "secret", "usage", team_id=1, job_id="j")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_without_primary_key_yields_nothing(self, MockSession) -> None:
        # A non-empty snapshot missing `billing_period_start` must not be yielded — merging on an
        # absent primary key column fails the sync permanently instead of producing an empty batch.
        rows, _ = _run("usage", {"monthly_limit": 2000, "concurrency": {"max": 2, "now": 1}}, MockSession)
        assert rows == []


class TestDailyUsageEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_exploded_sorted_rows(self, MockSession) -> None:
        rows, _ = _run("daily_usage", _USAGE_RESULT, MockSession)
        assert [r["date"] for r in rows] == ["2018-02-26", "2018-10-23"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_result_yields_nothing(self, MockSession) -> None:
        rows, _ = _run("daily_usage", {}, MockSession)
        assert rows == []


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("unavailable", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        # Retry-After: 0 keeps the retry wait at zero so the test doesn't sleep.
        _wire(session, [_response({}, status=status, retry_after=0), _response(_usage_body(_USAGE_RESULT))])
        rows = _rows(imagga_source("key", "secret", "usage", team_id=1, job_id="j"))
        assert len(rows) == 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"status": {"text": "unauthorized"}}, status=401)])
        with pytest.raises(HTTPError):
            _rows(imagga_source("key", "secret", "usage", team_id=1, job_id="j"))


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(IMAGGA_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("key", "secret") is expected

    @mock.patch(IMAGGA_SESSION_PATCH)
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False

    @mock.patch(IMAGGA_SESSION_PATCH)
    def test_redacts_secret_and_uses_basic_auth(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", "secret")
        # The secret is masked by value in logs/samples, and travels via Basic auth.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)
        auth = mock_session.return_value.get.call_args.kwargs["auth"]
        assert isinstance(auth, HTTPBasicAuth)
        assert (auth.username, auth.password) == ("key", "secret")


class TestImaggaSourceResponse:
    @parameterized.expand([("usage", ["billing_period_start"]), ("daily_usage", ["date"])])
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = imagga_source("key", "secret", endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    def test_daily_usage_partitions_on_stable_date(self) -> None:
        response = imagga_source("key", "secret", "daily_usage", team_id=1, job_id="j")
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    def test_usage_snapshot_is_not_partitioned(self) -> None:
        response = imagga_source("key", "secret", "usage", team_id=1, job_id="j")
        assert response.partition_keys is None

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            imagga_source("key", "secret", "nope", team_id=1, job_id="j")

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in IMAGGA_ENDPOINTS:
            response = imagga_source("key", "secret", endpoint, team_id=1, job_id="j")
            assert response.name == endpoint
            assert response.primary_keys == IMAGGA_ENDPOINTS[endpoint].primary_keys
