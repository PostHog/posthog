import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.sourcegraph._config import SourcegraphSourceConfig
from products.warehouse_sources.sources.sourcegraph.settings import SOURCEGRAPH_ENDPOINTS
from products.warehouse_sources.sources.sourcegraph.source import SourcegraphSource
from products.warehouse_sources.sources.sourcegraph.sourcegraph import (
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

MODULE = "products.warehouse_sources.sources.sourcegraph.sourcegraph"


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
    **inputs: Any,
) -> DriveResult:
    config = SourcegraphSourceConfig(host="sourcegraph.example.com", access_token="sgp_token")
    extra: dict[str, Any] = {"logger": logger} if logger is not None else {}
    return SourceDriver(SourcegraphSource(), config).run(endpoint, script, resume_state=resume_state, **extra, **inputs)


def _repositories_page(repo_ids: list[str], end_cursor: str | None = None) -> dict:
    return _connection_page(
        "repositories",
        [{"id": repo_id, "name": f"github.com/acme/{repo_id}"} for repo_id in repo_ids],
        end_cursor=end_cursor,
        has_next_page=end_cursor is not None,
    )


def _commits_page(oids: list[str], end_cursor: str | None = None) -> dict:
    nodes = [
        {
            "id": f"commit-{oid}",
            "oid": oid,
            "author": {"date": "2026-01-02T03:04:05Z", "person": {"name": "Ada", "email": "ada@example.com"}},
            "committer": {"date": "2026-01-03T03:04:05Z", "person": {"name": "Ada", "email": "ada@example.com"}},
        }
        for oid in oids
    ]
    ancestors = {"nodes": nodes, "pageInfo": {"endCursor": end_cursor, "hasNextPage": end_cursor is not None}}
    return {"data": {"node": {"defaultBranch": {"target": {"commit": {"ancestors": ancestors}}}}}}


def _fan_out_responder(repositories: dict[str | None, dict], children: dict[tuple[str, str | None], dict]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        body = request.json()
        variables = body["variables"]
        if "query RepositoryIds" in body["query"]:
            return _page(repositories[variables["after"]])
        return _page(children[(variables["id"], variables["after"])])

    return respond


def _event(event_id: str, timestamp: str) -> dict:
    return {"id": event_id, "exportedAt": timestamp, "payload": {"timestamp": timestamp, "feature": "search"}}


def _events_page(events: list[dict], end_cursor: str | None = None) -> dict:
    connection = {"nodes": events, "pageInfo": {"endCursor": end_cursor, "hasNextPage": end_cursor is not None}}
    return {"data": {"telemetry": {"exportedEvents": connection}}}


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

    def test_per_repository_endpoint_walks_every_repository_and_stages_the_next_position(self):
        # repo-b is empty (null defaultBranch), which must not end the walk or the parent paging.
        respond = _fan_out_responder(
            repositories={
                None: _repositories_page(["repo-a", "repo-b"], "repos-1"),
                "repos-1": _repositories_page(["repo-c"]),
            },
            children={
                ("repo-a", None): _commits_page(["a1", "a2"], end_cursor="2"),
                ("repo-a", "2"): _commits_page(["a3"]),
                ("repo-b", None): {"data": {"node": {"defaultBranch": None}}},
                ("repo-c", None): _commits_page(["c1"]),
            },
        )

        result = _run("commits", respond)

        assert result.raised is None
        assert [(row["repositoryId"], row["oid"]) for row in result.rows] == [
            ("repo-a", "a1"),
            ("repo-a", "a2"),
            ("repo-a", "a3"),
            ("repo-c", "c1"),
        ]
        assert result.rows[0]["repositoryName"] == "github.com/acme/repo-a"
        assert result.rows[0]["authoredAt"] == "2026-01-02T03:04:05Z"
        assert result.rows[0]["committedAt"] == "2026-01-03T03:04:05Z"
        assert result.saved_states == [
            SourcegraphResumeConfig(cursor="2", repositories_cursor=None, repository_id="repo-a"),
            SourcegraphResumeConfig(repositories_cursor=None, repository_id="repo-b"),
            SourcegraphResumeConfig(repositories_cursor="repos-1"),
        ]
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_per_repository_endpoint_resumes_inside_the_saved_repository(self):
        respond = _fan_out_responder(
            repositories={"repos-1": _repositories_page(["repo-c", "repo-d"])},
            children={("repo-d", "4"): _commits_page(["d5"])},
        )

        result = _run(
            "commits",
            respond,
            resume_state=SourcegraphResumeConfig(cursor="4", repositories_cursor="repos-1", repository_id="repo-d"),
        )

        assert result.raised is None
        assert [row["oid"] for row in result.rows] == ["d5"]
        assert [request.json()["variables"].get("id") for request in result.requests] == [None, "repo-d"]

    @parameterized.expand(
        [
            ("full_refresh", {}, None),
            (
                "incremental",
                {
                    "incremental_field": "committedAt",
                    "db_incremental_field_last_value": datetime(2026, 1, 2, tzinfo=UTC),
                },
                "2026-01-02T00:00:00Z",
            ),
            (
                "incremental_disabled",
                {
                    "incremental_field": "committedAt",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": datetime(2026, 1, 2, tzinfo=UTC),
                },
                None,
            ),
        ]
    )
    def test_commits_send_the_watermark_as_after_date(self, _name, inputs, expected_after_date):
        respond = _fan_out_responder(
            repositories={None: _repositories_page(["repo-a"])},
            children={("repo-a", None): _commits_page(["a1"])},
        )

        result = _run("commits", respond, **inputs)

        assert result.raised is None
        assert result.requests[1].json()["variables"]["afterDate"] == expected_after_date

    def test_per_repository_endpoint_stops_at_the_page_limit(self):
        endless = always(
            _page(
                {
                    "data": {
                        "repositories": {
                            "nodes": [{"id": "repo-a", "name": "a"}],
                            "pageInfo": {"endCursor": "c", "hasNextPage": True},
                        },
                        "node": {
                            "contributors": {
                                "nodes": [{"count": 1}],
                                "pageInfo": {"endCursor": "c", "hasNextPage": True},
                            }
                        },
                    }
                }
            )
        )

        with mock.patch(f"{MODULE}.MAX_PAGES_PER_RUN", 3):
            result = _run("contributors", endless)

        assert isinstance(result.raised, SourcegraphPaginationLimitError)
        assert len(result.requests) == 3

    def test_contributor_rows_carry_their_composite_key(self):
        respond = _fan_out_responder(
            repositories={None: _repositories_page(["repo-a"])},
            children={
                ("repo-a", None): {
                    "data": {
                        "node": {
                            "contributors": {
                                "nodes": [{"count": 7, "person": {"name": "Ada", "email": "ada@example.com"}}],
                                "pageInfo": {"endCursor": None, "hasNextPage": False},
                            }
                        }
                    }
                }
            },
        )

        result = _run("contributors", respond)

        assert result.raised is None
        assert result.response is not None
        primary_keys = result.response.primary_keys or []
        assert [{key: row[key] for key in primary_keys} for row in result.rows] == [
            {"repositoryId": "repo-a", "name": "Ada", "email": "ada@example.com"}
        ]

    @parameterized.expand(
        [
            ("full_refresh", {}, ["e1", "e2", "e3", "e4"], 2),
            (
                "incremental_stops_at_watermark",
                {"incremental_field": "timestamp", "db_incremental_field_last_value": datetime(2026, 1, 2, tzinfo=UTC)},
                ["e1", "e2", "e3"],
                2,
            ),
            (
                "incremental_watermark_on_first_page",
                {"incremental_field": "timestamp", "db_incremental_field_last_value": datetime(2026, 1, 4, tzinfo=UTC)},
                ["e1"],
                1,
            ),
        ]
    )
    def test_exported_events_are_read_newest_first_until_the_watermark(
        self, _name, inputs, expected_ids, expected_requests
    ):
        pages = [
            _page(
                _events_page(
                    [_event("e1", "2026-01-05T00:00:00.123456789Z"), _event("e2", "2026-01-03T00:00:00Z")],
                    end_cursor="cursor-1",
                )
            ),
            _page(_events_page([_event("e3", "2026-01-02T00:00:00Z"), _event("e4", "2026-01-01T00:00:00Z")])),
        ]

        result = _run("exported_events", pages, **inputs)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert len(result.requests) == expected_requests
        assert result.rows[0]["timestamp"] == "2026-01-05T00:00:00.123456789Z"

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

    def test_scoped_probe_of_a_per_repository_endpoint_runs_its_query_on_one_repository(self):
        respond = _fan_out_responder(
            repositories={None: _repositories_page(["repo-a"])},
            children={("repo-a", None): _commits_page(["a1"])},
        )

        with scripted_network(respond) as network:
            assert validate_credentials("sourcegraph.example.com", "sgp_token", schema_name="commits") == (True, None)

        assert [request.json()["variables"] for request in network.requests_log] == [
            {"first": 1, "after": None},
            {"first": 1, "after": None, "afterDate": None, "id": "repo-a"},
        ]

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
