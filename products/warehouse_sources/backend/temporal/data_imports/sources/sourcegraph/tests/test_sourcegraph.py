from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import SOURCEGRAPH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph import (
    SourcegraphHostNotAllowedError,
    SourcegraphQueryError,
    SourcegraphResumeConfig,
    SourcegraphRetryableError,
    _parse_retry_after,
    _retry_wait,
    get_endpoint_permissions,
    get_rows,
    normalize_host,
    sourcegraph_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph"


def _response(
    *, status_code: int = 200, json_data: Any = None, headers: dict[str, str] | None = None
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.headers = headers or {}
    response.json.return_value = json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://sourcegraph.example.com/.api/graphql",
            response=response,
        )
    return response


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


@pytest.fixture
def host_is_safe():
    with mock.patch(f"{MODULE}._is_host_safe", return_value=(True, None)):
        yield


@pytest.fixture
def session():
    with mock.patch(f"{MODULE}.make_tracked_session") as mock_make_session:
        yield mock_make_session.return_value


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
    def test_paginates_with_cursor_and_saves_state_after_yield(self, host_is_safe, session):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _connection_page(
            "repositories", [{"id": "r1"}, {"id": "r2"}], end_cursor="cursor-1", has_next_page=True
        )
        page2 = _connection_page("repositories", [{"id": "r3"}], end_cursor="cursor-2", has_next_page=False)
        session.post.side_effect = [_response(json_data=page1), _response(json_data=page2)]

        rows = get_rows("sourcegraph.example.com", "sgp_token", "repositories", mock.MagicMock(), manager, team_id=1)

        first_batch = next(rows)
        assert first_batch == [{"id": "r1"}, {"id": "r2"}]
        # State is saved only after the batch is yielded, so a crash re-yields (not skips) it.
        assert not manager.save_state.called

        second_batch = next(rows)
        assert second_batch == [{"id": "r3"}]
        manager.save_state.assert_called_once_with(SourcegraphResumeConfig(cursor="cursor-1"))

        with pytest.raises(StopIteration):
            next(rows)

        first_vars = session.post.call_args_list[0].kwargs["json"]["variables"]
        second_vars = session.post.call_args_list[1].kwargs["json"]["variables"]
        assert first_vars["after"] is None
        assert second_vars["after"] == "cursor-1"

    def test_resumes_from_saved_cursor(self, host_is_safe, session):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = SourcegraphResumeConfig(cursor="saved-cursor")
        session.post.return_value = _response(json_data=_connection_page("repositories", [{"id": "r9"}]))

        rows = list(
            get_rows("sourcegraph.example.com", "sgp_token", "repositories", mock.MagicMock(), manager, team_id=1)
        )

        assert rows == [[{"id": "r9"}]]
        assert session.post.call_args.kwargs["json"]["variables"]["after"] == "saved-cursor"

    def test_stops_on_empty_page_even_if_has_next_page(self, host_is_safe, session):
        # Termination guard: a malformed connection claiming more pages with no rows must not loop.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session.post.return_value = _response(
            json_data=_connection_page("repositories", [], end_cursor="cursor-1", has_next_page=True)
        )

        rows = list(
            get_rows("sourcegraph.example.com", "sgp_token", "repositories", mock.MagicMock(), manager, team_id=1)
        )

        assert rows == []
        assert session.post.call_count == 1

    def test_unpaginated_endpoint_fetches_once_and_warns_on_truncation(self, host_is_safe, session):
        manager = mock.MagicMock()
        logger = mock.MagicMock()
        session.post.return_value = _response(
            json_data={"data": {"organizations": {"nodes": [{"id": "o1"}], "totalCount": 1500}}}
        )

        rows = list(get_rows("sourcegraph.example.com", "sgp_token", "organizations", logger, manager, team_id=1))

        assert rows == [[{"id": "o1"}]]
        assert session.post.call_count == 1
        assert session.post.call_args.kwargs["json"]["variables"] == {"first": 1000}
        assert not manager.save_state.called
        assert logger.warning.called

    def test_graphql_error_raises_query_error(self, host_is_safe, session):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session.post.return_value = _response(json_data={"errors": [{"message": "must be site admin"}], "data": None})

        with pytest.raises(SourcegraphQueryError, match="must be site admin"):
            list(get_rows("sourcegraph.example.com", "sgp_token", "users", mock.MagicMock(), manager, team_id=1))

    def test_redirect_response_is_refused(self, host_is_safe, session):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session.post.return_value = _response(status_code=302)

        with pytest.raises(SourcegraphHostNotAllowedError):
            list(get_rows("sourcegraph.example.com", "sgp_token", "repositories", mock.MagicMock(), manager, team_id=1))

    def test_unsafe_host_is_blocked_before_any_request(self, session):
        manager = mock.MagicMock()
        with mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(SourcegraphHostNotAllowedError, match="blocked"):
                list(
                    get_rows("sourcegraph.internal", "sgp_token", "repositories", mock.MagicMock(), manager, team_id=1)
                )
        assert not session.post.called


class TestValidateCredentials:
    def test_valid_token_probes_current_user(self, session):
        session.post.return_value = _response(json_data={"data": {"currentUser": {"username": "alice"}}})

        assert validate_credentials("sourcegraph.example.com", "sgp_token") == (True, None)
        assert "currentUser" in session.post.call_args.kwargs["json"]["query"]

    def test_scoped_probe_runs_the_endpoint_query(self, session):
        session.post.return_value = _response(json_data=_connection_page("users", [{"id": "u1"}]))

        assert validate_credentials("sourcegraph.example.com", "sgp_token", schema_name="users") == (True, None)
        body = session.post.call_args.kwargs["json"]
        assert body["query"] == SOURCEGRAPH_ENDPOINTS["users"].query
        assert body["variables"] == {"first": 1, "after": None}

    def test_401_maps_to_invalid_token(self, session):
        session.post.return_value = _response(status_code=401)

        valid, error = validate_credentials("sourcegraph.example.com", "sgp_bad")

        assert valid is False
        assert error == "Invalid Sourcegraph access token"

    def test_graphql_error_surfaces_message(self, session):
        session.post.return_value = _response(json_data={"errors": [{"message": "not authenticated"}], "data": None})

        valid, error = validate_credentials("sourcegraph.example.com", "sgp_token", schema_name="users")

        assert valid is False
        assert error is not None and "not authenticated" in error

    @pytest.mark.parametrize("bad_host", ["", "   ", "not a host!"])
    def test_invalid_host_is_rejected_without_a_request(self, session, bad_host):
        valid, error = validate_credentials(bad_host, "sgp_token")

        assert valid is False
        assert error == "Invalid Sourcegraph URL"
        assert not session.post.called

    def test_unsafe_host_is_blocked(self, session):
        with mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "host not allowed")):
            valid, error = validate_credentials("sourcegraph.internal", "sgp_token", team_id=1)

        assert valid is False
        assert error == "host not allowed"
        assert not session.post.called


class TestGetEndpointPermissions:
    def test_denied_endpoints_report_reason_and_transient_failures_stay_reachable(self, session):
        def _post(url, **kwargs):
            query = kwargs["json"]["query"]
            if "query Users" in query:
                return _response(json_data={"errors": [{"message": "must be site admin"}], "data": None})
            if "query Organizations" in query:
                # Plain Timeout is not in the tenacity retry list, so this fails fast in the test
                # while still exercising the "transient network failure" branch.
                raise requests.Timeout("boom")
            return _response(json_data=_connection_page("repositories", [{"id": "r1"}]))

        session.post.side_effect = _post

        results = get_endpoint_permissions(
            "sourcegraph.example.com", "sgp_token", team_id=1, endpoints=["repositories", "users", "organizations"]
        )

        assert results["repositories"] is None
        assert results["users"] is not None and "must be site admin" in results["users"]
        # A network blip is not a missing scope.
        assert results["organizations"] is None


class TestSourcegraphSource:
    def test_repositories_response_is_partitioned_on_created_at(self):
        response = sourcegraph_source(
            "sourcegraph.example.com", "sgp_token", "repositories", mock.MagicMock(), mock.MagicMock(), team_id=1
        )

        assert response.name == "repositories"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        assert response.partition_format == "month"

    @pytest.mark.parametrize("endpoint", ["users", "organizations"])
    def test_small_tables_are_not_partitioned(self, endpoint):
        response = sourcegraph_source(
            "sourcegraph.example.com", "sgp_token", endpoint, mock.MagicMock(), mock.MagicMock(), team_id=1
        )

        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


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
