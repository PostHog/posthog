from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga import (
    BASE_URL,
    ImaggaRetryableError,
    _daily_usage_rows,
    _fetch_usage,
    _usage_snapshot_row,
    get_rows,
    imagga_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import IMAGGA_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.url: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.get_calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        response = self._responses.pop(0)
        response.url = url
        return response


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


class TestFetchUsage:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status)])
        with pytest.raises(ImaggaRetryableError):
            _fetch_usage(session, "key", "secret", mock.MagicMock())  # type: ignore[arg-type]

    def test_client_error_raises_http_error(self) -> None:
        session = _FakeSession([_FakeResponse(status_code=401, text="unauthorized")])
        with pytest.raises(requests.HTTPError):
            _fetch_usage(session, "key", "secret", mock.MagicMock())  # type: ignore[arg-type]

    def test_returns_result_object_and_sends_basic_auth(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"result": _USAGE_RESULT, "status": {"type": "success"}})])
        result = _fetch_usage(session, "key", "secret", mock.MagicMock())  # type: ignore[arg-type]
        assert result == _USAGE_RESULT
        # Credentials must ride in the Basic-auth header, not the URL.
        assert session.get_calls[0]["auth"] == ("key", "secret")
        assert session.get_calls[0]["url"] == f"{BASE_URL}/usage?concurrency=1"

    @parameterized.expand([("missing_result", {"status": {}}), ("null_result", {"result": None}), ("not_a_dict", [])])
    def test_missing_result_returns_empty_dict(self, _name: str, body: Any) -> None:
        session = _FakeSession([_FakeResponse(json_data=body)])
        assert _fetch_usage(session, "key", "secret", mock.MagicMock()) == {}  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga.make_tracked_session")
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials("key", "secret") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga.make_tracked_session")
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key", "secret") is False

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga.make_tracked_session")
    def test_redacts_secret_and_uses_basic_auth(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=200)
        validate_credentials("key", "secret")
        # The secret is masked by value in logs/samples, and travels via Basic auth.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)
        assert mock_session.return_value.get.call_args.kwargs["auth"] == ("key", "secret")


class TestGetRows:
    def _run(self, endpoint: str, result: dict[str, Any]) -> list[Any]:
        session = _FakeSession([_FakeResponse(json_data={"result": result})])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.imagga.imagga.make_tracked_session",
            return_value=session,
        ):
            return list(get_rows("key", "secret", endpoint, mock.MagicMock()))

    def test_usage_yields_single_snapshot_row(self) -> None:
        batches = self._run("usage", _USAGE_RESULT)
        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0]["billing_period_start"] == "18 of Oct, 2018"

    def test_daily_usage_yields_exploded_rows(self) -> None:
        batches = self._run("daily_usage", _USAGE_RESULT)
        assert [r["date"] for r in batches[0]] == ["2018-02-26", "2018-10-23"]

    @parameterized.expand([("usage", {}), ("daily_usage", {})])
    def test_empty_result_yields_nothing(self, endpoint: str, result: dict[str, Any]) -> None:
        assert self._run(endpoint, result) == []

    def test_usage_without_primary_key_yields_nothing(self) -> None:
        # A non-empty snapshot missing `billing_period_start` must not be yielded — merging on an
        # absent primary key column fails the sync permanently instead of producing an empty batch.
        result = {"monthly_limit": 2000, "concurrency": {"max": 2, "now": 1}}
        assert self._run("usage", result) == []

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError):
            self._run("nope", _USAGE_RESULT)


class TestImaggaSourceResponse:
    @parameterized.expand([("usage", ["billing_period_start"]), ("daily_usage", ["date"])])
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = imagga_source("key", "secret", endpoint, mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"

    def test_daily_usage_partitions_on_stable_date(self) -> None:
        response = imagga_source("key", "secret", "daily_usage", mock.MagicMock())
        assert response.partition_keys == ["date"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"

    def test_usage_snapshot_is_not_partitioned(self) -> None:
        response = imagga_source("key", "secret", "usage", mock.MagicMock())
        assert response.partition_keys is None

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in IMAGGA_ENDPOINTS:
            response = imagga_source("key", "secret", endpoint, mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == IMAGGA_ENDPOINTS[endpoint].primary_keys
