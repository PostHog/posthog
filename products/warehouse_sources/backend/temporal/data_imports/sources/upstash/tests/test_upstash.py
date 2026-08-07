import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    UPSTASH_API_BASE_URL,
    UPSTASH_ENDPOINTS,
    UPSTASH_ROOT_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.upstash import (
    upstash_source,
    validate_credentials,
)

# RESTClient never builds its own session here because upstash always passes a pre-built one; that
# session is created by make_tracked_session in the upstash module, so patch it there.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.upstash.upstash.make_tracked_session"
# tenacity sleeps between retries; patch it so retry-exhaustion tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(status: int, body: Any) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = b"" if body is None else json.dumps(body).encode()
    # raise_for_status embeds the URL in its message; keep it on the base host so the
    # get_non_retryable_errors matchers (tested in test_upstash_source) stay accurate.
    resp.url = f"{UPSTASH_API_BASE_URL}/teams"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses: list[Response]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with mock.patch(SESSION_PATCH) as make_session:
        session = mock.MagicMock()
        snapshots = _wire(session, responses)
        make_session.return_value = session
        rows = _rows(upstash_source(email="e", api_key="k", endpoint=endpoint, team_id=1, job_id="j"))
    return rows, snapshots


class TestListEndpoints:
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
        rows, snapshots = _run(endpoint, [_response(200, [{pk: "a"}, {pk: "b"}])])
        assert [r[pk] for r in rows] == ["a", "b"]
        assert [s["url"] for s in snapshots] == [expected_url]

    def test_non_list_response_raises(self) -> None:
        # A malformed body (object instead of array) must fail the sync loudly rather than silently
        # replace the warehouse table with zero rows.
        with pytest.raises(ValueError):
            _run("teams", [_response(200, {"unexpected": "shape"})])

    def test_empty_array_yields_no_rows(self) -> None:
        rows, _ = _run("teams", [_response(200, [])])
        assert rows == []

    def test_sensitive_fields_are_stripped_from_rows(self) -> None:
        # Vector index tokens are write-capable credentials; they must never reach warehouse columns.
        rows, _ = _run(
            "vector_indexes",
            [_response(200, [{"id": "i1", "name": "idx", "token": "secret", "read_only_token": "ro-secret"}])],
        )
        assert rows == [{"id": "i1", "name": "idx"}]


class TestStatsFanOut:
    def test_fans_out_per_database_and_stamps_database_id(self) -> None:
        rows, snapshots = _run(
            "redis_stats",
            [
                _response(200, [{"database_id": "db1"}, {"database_id": "db2"}]),
                _response(200, {"total_monthly_billing": 1.5}),
                _response(200, {"total_monthly_billing": 2.0}),
            ],
        )
        assert rows == [
            {"total_monthly_billing": 1.5, "database_id": "db1"},
            {"total_monthly_billing": 2.0, "database_id": "db2"},
        ]
        assert [s["url"] for s in snapshots] == [
            f"{UPSTASH_API_BASE_URL}/redis/databases",
            f"{UPSTASH_API_BASE_URL}/redis/stats/db1",
            f"{UPSTASH_API_BASE_URL}/redis/stats/db2",
        ]

    def test_skips_database_deleted_between_enumeration_and_stats_fetch(self) -> None:
        rows, _ = _run(
            "redis_stats",
            [
                _response(200, [{"database_id": "db1"}, {"database_id": "db2"}]),
                _response(404, {"error": "database not found"}),
                _response(200, {"total_monthly_billing": 2.0}),
            ],
        )
        assert rows == [{"total_monthly_billing": 2.0, "database_id": "db2"}]

    @mock.patch(SLEEP_PATCH)
    def test_non_404_error_during_fan_out_propagates(self, _sleep: Any) -> None:
        # A persistent 5xx while fetching stats fails the sync (after the client's retries) rather
        # than being swallowed like a 404.
        calls = {"n": 0}

        def _send(*_a: Any, **_k: Any) -> Response:
            calls["n"] += 1
            # First call is the parent databases list; every stats fetch after it 500s.
            if calls["n"] == 1:
                return _response(200, [{"database_id": "db1"}])
            return _response(500, {"error": "boom"})

        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.headers = {}
            session.prepare_request.side_effect = lambda request: mock.MagicMock()
            session.send.side_effect = _send
            make_session.return_value = session
            with pytest.raises(Exception):
                _rows(upstash_source(email="e", api_key="k", endpoint="redis_stats", team_id=1, job_id="j"))
            # The parent succeeded once; the child 500 was retried several times before failing.
            assert calls["n"] > 2

    def test_database_row_missing_id_raises(self) -> None:
        # The stats sync fans out over every database id; a row missing its id must fail the sync
        # rather than be silently dropped, which would yield partial usage/billing data.
        with pytest.raises(ValueError):
            _run(
                "redis_stats",
                [
                    _response(200, [{"database_id": "db1"}, {"not_the_id": "x"}]),
                    _response(200, {"total_monthly_billing": 1.5}),
                ],
            )


class TestHttpSampleCapture:
    # Responses that carry secrets (vector index tokens) must be excluded from HTTP sample capture,
    # since the generic scrubber does not redact fields named `token`. Other endpoints keep capture on.
    @parameterized.expand([("vector_indexes", False), ("teams", True)])
    def test_capture_flag_tracks_sensitive_endpoints(self, endpoint: str, expected_capture: bool) -> None:
        recorded: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> Any:
            recorded["capture"] = kwargs.get("capture", True)
            return mock.MagicMock(headers={})

        with mock.patch(SESSION_PATCH, fake_session):
            upstash_source(email="e", api_key="k", endpoint=endpoint, team_id=1, job_id="j")
        assert recorded["capture"] is expected_capture


class TestRetryClassification:
    @mock.patch(SLEEP_PATCH)
    def test_persistent_5xx_raises_after_retries(self, _sleep: Any) -> None:
        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.headers = {}
            session.prepare_request.side_effect = lambda request: mock.MagicMock()
            session.send.side_effect = lambda *a, **k: _response(500, {"error": "boom"})
            make_session.return_value = session
            with pytest.raises(Exception):
                _rows(upstash_source(email="e", api_key="k", endpoint="teams", team_id=1, job_id="j"))
            # The client retries a 5xx several times before giving up (default 5 attempts).
            assert session.send.call_count > 1

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_raise_immediately(self, status: int) -> None:
        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.headers = {}
            session.prepare_request.side_effect = lambda request: mock.MagicMock()
            session.send.side_effect = lambda *a, **k: _response(status, {"error": "denied"})
            make_session.return_value = session
            with pytest.raises(requests.HTTPError):
                _rows(upstash_source(email="e", api_key="k", endpoint="teams", team_id=1, job_id="j"))
            # A credential error is not retried.
            assert session.send.call_count == 1


class TestValidateCredentials:
    # Only a definitive 401/403 rejects the credentials. 429/5xx are transient (retried during sync)
    # and must not block source creation during an Upstash outage or rate-limit window.
    @parameterized.expand([(200, True), (401, False), (403, False), (429, True), (500, True)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = mock.MagicMock(status_code=status)
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
            ok, error = validate_credentials("e", "k")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_probes_teams_endpoint_with_basic_auth(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
            validate_credentials("me@example.com", "secret")
        args, kwargs = session.get.call_args
        assert args[0] == f"{UPSTASH_API_BASE_URL}/teams"
        auth = kwargs["auth"]
        assert (auth.username, auth.password) == ("me@example.com", "secret")

    def test_request_exception_does_not_block_creation(self) -> None:
        # An unreachable API is transient, not a credential rejection; a genuine auth failure still
        # surfaces at sync time.
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
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
        with mock.patch(SESSION_PATCH, lambda *a, **k: mock.MagicMock(headers={})):
            response = upstash_source(email="e", api_key="k", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        # Full refresh, replaced wholesale each sync; asc is the pipeline default.
        assert response.sort_mode == "asc"

    def test_every_declared_endpoint_has_a_response(self) -> None:
        with mock.patch(SESSION_PATCH, lambda *a, **k: mock.MagicMock(headers={})):
            for endpoint in UPSTASH_ENDPOINTS:
                response = upstash_source(email="e", api_key="k", endpoint=endpoint, team_id=1, job_id="j")
                assert response.primary_keys == UPSTASH_ENDPOINTS[endpoint].primary_keys
