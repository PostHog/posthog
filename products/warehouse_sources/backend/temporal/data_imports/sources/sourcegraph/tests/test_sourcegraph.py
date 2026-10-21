import threading
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sourcegraph import (
    SourcegraphSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import SOURCEGRAPH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.source import SourcegraphSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph import (
    MAX_RESPONSE_BYTES,
    SourcegraphHostNotAllowedError,
    SourcegraphPaginationLimitError,
    SourcegraphQueryError,
    SourcegraphResponseTimeoutError,
    SourcegraphResponseTooLargeError,
    SourcegraphResumeConfig,
    SourcegraphRetryableError,
    _parse_retry_after,
    _read_bounded,
    _retry_wait,
    get_endpoint_permissions,
    normalize_host,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph"


def _connection_page(
    data_path: str, nodes: list[dict], *, end_cursor: str | None = None, has_next_page: bool = False
) -> dict:
    return {
        "data": {
            data_path: {
                "nodes": nodes,
                "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_next_page},
            }
        }
    }


def _page(json_data: Any = None, status: int = 200, headers: dict[str, str] | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json_data, headers=headers or {})


def _run(
    endpoint: str,
    script: Script,
    resume_state: SourcegraphResumeConfig | None = None,
    logger: Any = None,
) -> DriveResult:
    config = SourcegraphSourceConfig(host="sourcegraph.example.com", access_token="sgp_token")
    extra: dict[str, Any] = {"logger": logger} if logger is not None else {}
    return SourceDriver(SourcegraphSource(), config).run(endpoint, script, resume_state=resume_state, **extra)


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("sourcegraph.example.com", "sourcegraph.example.com"),
            ("https://sourcegraph.example.com", "sourcegraph.example.com"),
            ("http://sourcegraph.example.com/", "sourcegraph.example.com"),
            ("  sourcegraph.example.com  ", "sourcegraph.example.com"),
            ("sourcegraph.example.com/.api/graphql", "sourcegraph.example.com"),
            ("https://sourcegraph.com/search", "sourcegraph.com"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestGetRows:
    def test_paginates_with_cursor_and_saves_state_after_yield(self):
        page1 = _connection_page(
            "repositories", [{"id": "r1"}, {"id": "r2"}], end_cursor="cursor-1", has_next_page=True
        )
        page2 = _connection_page("repositories", [{"id": "r3"}], end_cursor="cursor-2", has_next_page=False)

        result = _run("repositories", [_page(page1), _page(page2)])

        assert result.raised is None
        assert result.items == [[{"id": "r1"}, {"id": "r2"}], [{"id": "r3"}]]
        # Only the first page has a successor, so only its cursor is saved.
        assert result.saved_states == [SourcegraphResumeConfig(cursor="cursor-1")]
        assert result.requests[0].json()["variables"]["after"] is None
        assert result.requests[1].json()["variables"]["after"] == "cursor-1"

    def test_resumes_from_saved_cursor(self):
        result = _run(
            "repositories",
            [_page(_connection_page("repositories", [{"id": "r9"}]))],
            resume_state=SourcegraphResumeConfig(cursor="saved-cursor"),
        )

        assert result.items == [[{"id": "r9"}]]
        assert result.requests[0].json()["variables"]["after"] == "saved-cursor"

    def test_stops_on_empty_page_even_if_has_next_page(self):
        # Termination guard: a malformed connection claiming more pages with no rows must not loop.
        result = _run(
            "repositories",
            [_page(_connection_page("repositories", [], end_cursor="cursor-1", has_next_page=True))],
        )

        assert result.items == []
        assert len(result.requests) == 1

    def test_endless_pagination_stops_at_the_page_limit(self):
        # A customer-controlled host that always returns a full page + fresh cursor + hasNextPage
        # must fail the run at the page cap rather than loop until the activity's week-long timeout.
        endless = always(_page(_connection_page("repositories", [{"id": "r"}], end_cursor="c", has_next_page=True)))

        with mock.patch(f"{MODULE}.MAX_PAGES_PER_RUN", 3):
            result = _run("repositories", endless)

        assert isinstance(result.raised, SourcegraphPaginationLimitError)
        assert len(result.requests) == 3

    def test_endless_pagination_stops_at_the_deadline(self):
        # The cumulative wall-clock bound catches a host that drips full pages slowly enough to stay
        # under the page cap; a deadline already in the past trips right after the first page.
        endless = always(_page(_connection_page("repositories", [{"id": "r"}], end_cursor="c", has_next_page=True)))

        with mock.patch(f"{MODULE}.MAX_PAGINATION_SECONDS", -1):
            result = _run("repositories", endless)

        assert isinstance(result.raised, SourcegraphPaginationLimitError)
        assert len(result.requests) == 1

    def test_unpaginated_endpoint_fetches_once_and_warns_on_truncation(self):
        logger = mock.MagicMock()

        result = _run(
            "organizations",
            [_page({"data": {"organizations": {"nodes": [{"id": "o1"}], "totalCount": 1500}}})],
            logger=logger,
        )

        assert result.items == [[{"id": "o1"}]]
        assert len(result.requests) == 1
        assert result.requests[0].json()["variables"] == {"first": 1000}
        assert result.saved_states == []
        assert logger.warning.called

    def test_graphql_error_raises_query_error(self):
        result = _run("users", [_page({"errors": [{"message": "must be site admin"}], "data": None})])

        assert isinstance(result.raised, SourcegraphQueryError)
        assert "must be site admin" in str(result.raised)

    def test_redirect_response_is_refused(self):
        result = _run("repositories", [_page(status=302, headers={"Location": "https://elsewhere.example.com/"})])

        assert isinstance(result.raised, SourcegraphHostNotAllowedError)
        assert len(result.requests) == 1

    def test_unsafe_host_is_blocked_before_any_request(self):
        with mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "blocked")):
            result = _run("repositories", [])

        assert isinstance(result.raised, SourcegraphHostNotAllowedError)
        assert "blocked" in str(result.raised)
        assert result.requests == []


class TestValidateCredentials:
    def test_valid_token_probes_current_user(self):
        with scripted_network([_page({"data": {"currentUser": {"username": "alice"}}})]) as network:
            assert validate_credentials("sourcegraph.example.com", "sgp_token") == (True, None)
        assert "currentUser" in network.requests_log[0].json()["query"]

    def test_scoped_probe_runs_the_endpoint_query(self):
        with scripted_network([_page(_connection_page("users", [{"id": "u1"}]))]) as network:
            assert validate_credentials("sourcegraph.example.com", "sgp_token", schema_name="users") == (True, None)
        body = network.requests_log[0].json()
        assert body["query"] == SOURCEGRAPH_ENDPOINTS["users"].query
        assert body["variables"] == {"first": 1, "after": None}

    def test_401_maps_to_invalid_token(self):
        with scripted_network([_page(status=401)]):
            valid, error = validate_credentials("sourcegraph.example.com", "sgp_bad")

        assert valid is False
        assert error == "Invalid Sourcegraph access token"

    def test_graphql_error_surfaces_message(self):
        with scripted_network([_page({"errors": [{"message": "not authenticated"}], "data": None})]):
            valid, error = validate_credentials("sourcegraph.example.com", "sgp_token", schema_name="users")

        assert valid is False
        assert error is not None and "not authenticated" in error

    @pytest.mark.parametrize("bad_host", ["", "   ", "not a host!"])
    def test_invalid_host_is_rejected_without_a_request(self, bad_host):
        with scripted_network([]) as network:
            valid, error = validate_credentials(bad_host, "sgp_token")

        assert valid is False
        assert error == "Invalid Sourcegraph URL"
        assert network.requests_log == []

    def test_unsafe_host_is_blocked(self):
        with scripted_network([]) as network:
            with mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "host not allowed")):
                valid, error = validate_credentials("sourcegraph.internal", "sgp_token", team_id=1)

        assert valid is False
        assert error == "host not allowed"
        assert network.requests_log == []


class TestGetEndpointPermissions:
    def test_denied_endpoints_report_reason_and_transient_failures_stay_reachable(self):
        def _post(request: RecordedRequest) -> ScriptedResponse:
            query = request.json()["query"]
            if "query Users" in query:
                return _page({"errors": [{"message": "must be site admin"}], "data": None})
            if "query Organizations" in query:
                raise TimeoutError("timed out")
            return _page(_connection_page("repositories", [{"id": "r1"}]))

        with scripted_network(_post):
            results = get_endpoint_permissions(
                "sourcegraph.example.com", "sgp_token", team_id=1, endpoints=["repositories", "users", "organizations"]
            )

        assert results["repositories"] is None
        assert results["users"] is not None and "must be site admin" in results["users"]
        # A network blip is not a missing scope.
        assert results["organizations"] is None


class TestSourcegraphSource:
    def test_repositories_response_is_partitioned_on_created_at(self):
        response = _run("repositories", always(_page({"data": {}}))).response

        assert response is not None
        assert response.name == "repositories"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        assert response.partition_format == "month"

    @pytest.mark.parametrize("endpoint", ["users", "organizations"])
    def test_small_tables_are_not_partitioned(self, endpoint):
        response = _run(endpoint, always(_page({"data": {}}))).response

        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestReadBounded:
    # The Sourcegraph host is customer-controlled, so a malicious 200 body must fail the sync
    # rather than exhaust or indefinitely occupy a worker.
    def test_oversized_body_is_rejected(self):
        response = mock.MagicMock()
        response.iter_content.return_value = iter([b"x" * 10, b"y" * 10])

        with pytest.raises(SourcegraphResponseTooLargeError):
            _read_bounded(response, max_bytes=15)

    def test_slow_drip_body_hits_the_deadline(self):
        response = mock.MagicMock()
        response.iter_content.return_value = iter([b"a", b"b", b"c"])

        # First call sets the deadline; the next read is past it, so a body that arrives as many
        # quick chunks but overruns the deadline is aborted by the in-loop check.
        with mock.patch(f"{MODULE}.time.monotonic", side_effect=[0.0, 100.0]):
            with pytest.raises(SourcegraphResponseTimeoutError):
                _read_bounded(response, max_bytes=1000, max_seconds=1.0)

    def test_watchdog_aborts_a_read_blocked_past_the_deadline(self):
        # A real slow-drip body blocks inside a single iter_content read, so the in-loop deadline
        # check never regains control — only the watchdog closing the response can interrupt it.
        closed = threading.Event()

        def blocking_read(*args: Any, **kwargs: Any):
            # Block like a socket read would until the watchdog force-closes the response.
            if not closed.wait(5.0):
                raise AssertionError("watchdog did not close the response")
            raise requests.exceptions.ChunkedEncodingError("connection closed")
            yield  # type: ignore[unreachable]  # makes this a generator so iter_content returns an iterator

        response = mock.MagicMock()
        response.iter_content.side_effect = blocking_read
        response.close.side_effect = lambda: closed.set()

        with pytest.raises(SourcegraphResponseTimeoutError):
            _read_bounded(response, max_bytes=1000, max_seconds=0.1)

    def test_bounded_body_is_returned(self):
        response = mock.MagicMock()
        response.iter_content.return_value = iter([b'{"data', b'": {}}'])

        assert _read_bounded(response, max_bytes=MAX_RESPONSE_BYTES) == b'{"data": {}}'


class TestRetryHelpers:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ({"Retry-After": "7"}, 7.0),
            ({"Retry-After": "999"}, 60.0),
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, header, expected):
        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        state = mock.MagicMock()
        state.outcome.exception.return_value = SourcegraphRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
