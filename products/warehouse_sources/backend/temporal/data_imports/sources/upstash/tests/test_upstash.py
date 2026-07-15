from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.upstash import upstash
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    UPSTASH_API_BASE_URL,
    UPSTASH_ENDPOINTS,
    UPSTASH_ROOT_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.upstash import (
    UpstashRetryableError,
    _fetch,
    get_rows,
    upstash_source,
    validate_credentials,
)


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def _collect(endpoint: str, url_responses: dict[str, Any]) -> tuple[list[dict], list[str]]:
    """Run get_rows with _fetch stubbed by a URL->response (or exception) map. Records call order."""
    calls: list[str] = []

    def fake_fetch(session: Any, url: str, auth: Any, logger: Any) -> Any:
        calls.append(url)
        result = url_responses[url]
        if isinstance(result, Exception):
            raise result
        return result

    with patch.object(upstash, "_fetch", fake_fetch):
        rows = list(get_rows(email="e", api_key="k", endpoint=endpoint, logger=MagicMock()))
    return rows, calls


class TestGetRowsListEndpoints:
    @parameterized.expand(
        [
            ("redis_databases", f"{UPSTASH_API_BASE_URL}/redis/databases", "database_id"),
            ("teams", f"{UPSTASH_API_BASE_URL}/teams", "team_id"),
            ("vector_indexes", f"{UPSTASH_API_BASE_URL}/vector/index", "id"),
            # Audit logs are served from the unversioned host, not api.upstash.com/v2.
            ("audit_logs", f"{UPSTASH_ROOT_BASE_URL}/auditlogs", "log_id"),
        ]
    )
    def test_yields_dicts_from_raw_array_at_expected_url(self, endpoint: str, expected_url: str, pk: str) -> None:
        rows, calls = _collect(endpoint, {expected_url: [{pk: "a"}, {pk: "b"}]})
        assert [r[pk] for r in rows] == ["a", "b"]
        assert calls == [expected_url]

    def test_non_list_response_raises(self) -> None:
        # A malformed body (object instead of array) must fail the sync loudly rather than silently
        # replace the warehouse table with zero rows.
        url = f"{UPSTASH_API_BASE_URL}/teams"
        with pytest.raises(ValueError):
            _collect("teams", {url: {"unexpected": "shape"}})

    def test_non_dict_items_are_skipped(self) -> None:
        url = f"{UPSTASH_API_BASE_URL}/teams"
        rows, _ = _collect("teams", {url: [{"team_id": "t1"}, "garbage", None]})
        assert [r["team_id"] for r in rows] == ["t1"]

    def test_sensitive_fields_are_stripped_from_rows(self) -> None:
        # Vector index tokens are write-capable credentials; they must never reach warehouse columns.
        url = f"{UPSTASH_API_BASE_URL}/vector/index"
        rows, _ = _collect(
            "vector_indexes",
            {url: [{"id": "i1", "name": "idx", "token": "secret", "read_only_token": "ro-secret"}]},
        )
        assert rows == [{"id": "i1", "name": "idx"}]


class TestGetRowsStatsFanOut:
    def test_fans_out_per_database_and_stamps_database_id(self) -> None:
        db_url = f"{UPSTASH_API_BASE_URL}/redis/databases"
        stats1 = f"{UPSTASH_API_BASE_URL}/redis/stats/db1"
        stats2 = f"{UPSTASH_API_BASE_URL}/redis/stats/db2"
        rows, calls = _collect(
            "redis_stats",
            {
                db_url: [{"database_id": "db1"}, {"database_id": "db2"}],
                stats1: {"total_monthly_billing": 1.5},
                stats2: {"total_monthly_billing": 2.0},
            },
        )
        assert rows == [
            {"total_monthly_billing": 1.5, "database_id": "db1"},
            {"total_monthly_billing": 2.0, "database_id": "db2"},
        ]
        assert calls == [db_url, stats1, stats2]

    def test_skips_database_deleted_between_enumeration_and_stats_fetch(self) -> None:
        db_url = f"{UPSTASH_API_BASE_URL}/redis/databases"
        stats1 = f"{UPSTASH_API_BASE_URL}/redis/stats/db1"
        stats2 = f"{UPSTASH_API_BASE_URL}/redis/stats/db2"
        rows, _ = _collect(
            "redis_stats",
            {
                db_url: [{"database_id": "db1"}, {"database_id": "db2"}],
                stats1: _http_error(404),
                stats2: {"total_monthly_billing": 2.0},
            },
        )
        assert rows == [{"total_monthly_billing": 2.0, "database_id": "db2"}]

    def test_non_404_error_during_fan_out_propagates(self) -> None:
        db_url = f"{UPSTASH_API_BASE_URL}/redis/databases"
        stats1 = f"{UPSTASH_API_BASE_URL}/redis/stats/db1"
        try:
            _collect("redis_stats", {db_url: [{"database_id": "db1"}], stats1: _http_error(500)})
        except requests.HTTPError as exc:
            assert exc.response is not None and exc.response.status_code == 500
        else:
            raise AssertionError("expected the 500 to propagate")

    def test_database_row_missing_id_raises(self) -> None:
        # The stats sync fans out over every database id; a row missing its id must fail the sync
        # rather than be silently dropped, which would yield partial usage/billing data.
        db_url = f"{UPSTASH_API_BASE_URL}/redis/databases"
        with pytest.raises(KeyError):
            _collect("redis_stats", {db_url: [{"database_id": "db1"}, {"not_the_id": "x"}]})


class TestHttpSampleCapture:
    # Responses that carry secrets (vector index tokens) must be excluded from HTTP sample capture,
    # since the generic scrubber does not redact fields named `token`. Other endpoints keep capture on.
    @parameterized.expand([("vector_indexes", False), ("teams", True)])
    def test_capture_flag_tracks_sensitive_endpoints(self, endpoint: str, expected_capture: bool) -> None:
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> Any:
            captured["capture"] = kwargs.get("capture", True)
            return MagicMock()

        with patch.object(upstash, "make_tracked_session", fake_session):
            with patch.object(upstash, "_fetch", lambda *a, **k: []):
                list(get_rows(email="e", api_key="k", endpoint=endpoint, logger=MagicMock()))
        assert captured["capture"] is expected_capture


class TestFetchRetryClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        # stop_after_attempt exhausts and reraises the last UpstashRetryableError.
        try:
            _fetch(session, "https://api.upstash.com/v2/teams", ("e", "k"), MagicMock())
        except UpstashRetryableError:
            pass
        else:
            raise AssertionError("expected UpstashRetryableError")

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_for_status(self, status: int) -> None:
        response = requests.Response()
        response.status_code = status
        response.url = "https://api.upstash.com/v2/teams"
        session = MagicMock()
        session.get.return_value = response
        try:
            _fetch(session, response.url, ("e", "k"), MagicMock())
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("expected HTTPError from raise_for_status")


class TestValidateCredentials:
    # Only a definitive 401/403 rejects the credentials. 429/5xx are transient (retried during sync)
    # and must not block source creation during an Upstash outage or rate-limit window.
    @parameterized.expand([(200, True), (401, False), (403, False), (429, True), (500, True)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(upstash, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("e", "k")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_probes_teams_endpoint_with_basic_auth(self) -> None:
        response = requests.Response()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(upstash, "make_tracked_session", lambda *a, **k: session):
            validate_credentials("me@example.com", "secret")
        _, kwargs = session.get.call_args
        assert session.get.call_args[0][0] == f"{UPSTASH_API_BASE_URL}/teams"
        assert kwargs["auth"] == ("me@example.com", "secret")

    def test_request_exception_does_not_block_creation(self) -> None:
        # An unreachable API is transient, not a credential rejection; a genuine auth failure still
        # surfaces at sync time.
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(upstash, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("e", "k")
        assert ok is True
        assert error is None


class TestUpstashSource:
    @parameterized.expand(
        [
            ("redis_databases", ["database_id"]),
            ("redis_stats", ["database_id"]),
            ("teams", ["team_id"]),
            ("vector_indexes", ["id"]),
            ("audit_logs", ["log_id"]),
        ]
    )
    def test_source_response_primary_keys_and_sort(self, endpoint: str, expected_pk: list[str]) -> None:
        response = upstash_source(email="e", api_key="k", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        # Full refresh, replaced wholesale each sync; asc is the pipeline default.
        assert response.sort_mode == "asc"

    def test_every_declared_endpoint_has_a_response(self) -> None:
        for endpoint in UPSTASH_ENDPOINTS:
            response = upstash_source(email="e", api_key="k", endpoint=endpoint, logger=MagicMock())
            assert response.primary_keys == UPSTASH_ENDPOINTS[endpoint].primary_keys
