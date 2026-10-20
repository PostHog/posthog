import re
from typing import Any

from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linear import LinearSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear import (
    _FLOAT_FIELDS,
    LINEAR_MAX_RETRY_ATTEMPTS,
    LinearResumeConfig,
    LinearRetryableError,
    _parse_retry_after,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.queries import QUERIES
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LINEAR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.source import LinearSource


def _graphql_query_name(endpoint_name: str) -> str:
    config = LINEAR_ENDPOINTS[endpoint_name]
    return config.graphql_query_name or endpoint_name


def _make_rate_limited_response(headers: dict[str, str] | None = None) -> MagicMock:
    """Mimic Linear's HTTP-level 429: an HTML body that fails JSON parsing."""
    response = MagicMock()
    response.status_code = 429
    response.ok = False
    response.reason = "Too Many Requests"
    response.text = "<!DOCTYPE html><html><head><title>Rate limited</title></head></html>"
    response.headers = headers or {}
    response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
    return response


class _LinearSourceWithToken(LinearSource):
    def _get_access_token(self, config: LinearSourceConfig, team_id: int) -> str:
        return "tok"


def _driver() -> SourceDriver:
    return SourceDriver(_LinearSourceWithToken(), LinearSourceConfig(linear_integration_id=1))


def _page(
    query_name: str, nodes: list[dict[str, Any]], has_next_page: bool = False, end_cursor: str | None = None
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {query_name: {"nodes": nodes, "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor}}}
        }
    )


# (has_next, end_cursor) per page. Nodes are synthetic; only pagination matters.
PageSpec = tuple[bool, str | None]


class TestMakePaginatedRequest:
    @parameterized.expand(
        [
            # Fresh runs
            ("fresh_multi_page", None, [(True, "c1"), (True, "c2"), (False, None)], None, ["c1", "c2"], False),
            ("fresh_single_empty", None, [(False, None)], None, [], False),
            ("fresh_with_filter", None, [(True, "c1"), (False, None)], "2026-01-01T00:00:00Z", ["c1"], False),
            # Resume runs
            ("resume_final_page_only", "saved-c", [(False, None)], None, [], True),
            ("resume_then_more_pages", "saved-c", [(True, "c1"), (False, None)], None, ["c1"], True),
            (
                "resume_with_filter",
                "saved-c",
                [(True, "c1"), (False, None)],
                "2026-01-01T00:00:00Z",
                ["c1"],
                True,
            ),
        ]
    )
    def test_pagination_state(
        self,
        _name: str,
        saved_cursor: str | None,
        page_specs: list[PageSpec],
        filter_gte: str | None,
        expected_save_cursors: list[str],
        first_request_has_cursor: bool,
    ) -> None:
        result = _driver().run(
            "issues",
            [_page("issues", [{"id": f"{i}"}], has_next, end) for i, (has_next, end) in enumerate(page_specs)],
            resume_state=LinearResumeConfig(cursor=saved_cursor) if saved_cursor is not None else None,
            incremental_field="updatedAt" if filter_gte is not None else None,
            db_incremental_field_last_value=filter_gte,
        )
        assert result.raised is None
        variables = [request.json()["variables"] for request in result.requests]

        # Resume path: first request carries the saved cursor; fresh path: no cursor on first request.
        if first_request_has_cursor:
            assert variables[0]["cursor"] == saved_cursor
        else:
            assert "cursor" not in variables[0]

        # Each non-final page checkpoints the cursor of the next page.
        assert result.saved_states == [LinearResumeConfig(cursor=c) for c in expected_save_cursors]
        assert result.rows == [{"id": f"{i}"} for i in range(len(page_specs))]

        # The updated_at filter, if any, must be applied on every page including the resumed first request.
        if filter_gte is not None:
            for request_variables in variables:
                assert request_variables["filter"] == {"updatedAt": {"gt": filter_gte}}

    @parameterized.expand([("null_end_cursor", None), ("empty_end_cursor", "")])
    def test_raises_when_has_next_page_but_cursor_missing(
        self,
        _name: str,
        bad_cursor: str | None,
    ) -> None:
        result = _driver().run("issues", [_page("issues", [{"id": "a"}], True, bad_cursor)])

        assert isinstance(result.raised, Exception)
        assert "endCursor is empty" in str(result.raised)
        assert result.saved_states == []
        assert len(result.requests) == 1

    def test_persistent_http_429_raises_retryable_error(self) -> None:
        result = _driver().run("issues", always(ScriptedResponse(status=429, body=b"<html>Rate limited</html>")))

        assert isinstance(result.raised, LinearRetryableError)
        assert len(result.requests) == LINEAR_MAX_RETRY_ATTEMPTS

    @parameterized.expand(
        [
            ("read_timeout", requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")),
            ("connection_reset", requests.exceptions.ConnectionError("Connection aborted")),
            # ChunkedEncodingError is not a ConnectionError subclass, so it must be listed explicitly
            # to ride the retry path instead of failing the activity on a connection broken mid-body.
            (
                "chunked_encoding_broken",
                requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength"),
            ),
        ]
    )
    def test_transient_network_error_is_retried_then_succeeds(
        self,
        _name: str,
        transient_exc: Exception,
    ) -> None:
        # Linear's POSTs get no transport-level retry, so a transient network error must be folded
        # into the application-level backoff rather than escaping on the first attempt.
        result = _driver().run("issues", [transient_exc, _page("issues", [{"id": "a"}])])

        assert result.raised is None
        assert result.items == [[{"id": "a"}]]
        assert len(result.requests) == 2

    def test_persistent_network_error_raises_retryable_error(self) -> None:
        result = _driver().run("issues", always(ConnectionError("Connection aborted")))

        assert isinstance(result.raised, LinearRetryableError)
        assert set(result.paths) == {"/graphql"}

    def test_persistent_truncated_response_raises_retryable_error_without_leaking_body(self) -> None:
        # The partial body can embed customer data, so the retryable error must describe the failure
        # without echoing response.text.
        body = '{"data":{"issues":{"nodes":[{"title":"secret customer issue"'
        result = _driver().run("issues", always(ScriptedResponse(body=body.encode())))

        assert isinstance(result.raised, LinearRetryableError)
        assert len(result.requests) == LINEAR_MAX_RETRY_ATTEMPTS
        assert "secret customer issue" not in str(result.raised)

    def test_graphql_internal_server_error_is_retried_then_succeeds(self) -> None:
        # Linear's GraphQL layer can wrap a resolver-side blip as a 200 with a generic
        # "Internal server error" message instead of an HTTP 5xx. It must be retried with
        # backoff like the status-code 5xx case, not surfaced as a non-retryable Exception.
        result = _driver().run(
            "issues",
            [ScriptedResponse(json={"errors": [{"message": "Internal server error"}]}), _page("issues", [{"id": "a"}])],
        )

        assert result.raised is None
        assert result.items == [[{"id": "a"}]]
        assert len(result.requests) == 2

    def test_persistent_graphql_internal_server_error_raises_retryable_error(self) -> None:
        result = _driver().run(
            "issues", always(ScriptedResponse(json={"errors": [{"message": "Internal server error"}]}))
        )

        assert isinstance(result.raised, LinearRetryableError)
        assert len(result.requests) == LINEAR_MAX_RETRY_ATTEMPTS


class TestFloatFieldCoercion:
    @parameterized.expand(
        [(endpoint, field) for endpoint, fields in _FLOAT_FIELDS.items() for field in fields],
        name_func=lambda func, _num, param: f"{func.__name__}_{param.args[0]}_{param.args[1]}",
    )
    def test_whole_number_float_field_is_coerced_to_float(self, endpoint_name: str, field_name: str) -> None:
        # Whole values (0, 1) of Linear's Float fields arrive as JSON ints. Left as ints, a
        # table-creating batch of only whole values infers int64 and the first fractional value
        # wedges the sync with ArrowInvalid. The source must yield floats so the column always
        # infers as float64.
        result = _driver().run(
            endpoint_name,
            [
                _page(
                    _graphql_query_name(endpoint_name),
                    [{"id": "a", field_name: 0}, {"id": "b", field_name: 1}, {"id": "c", field_name: None}],
                )
            ],
        )

        assert result.raised is None
        values = [node[field_name] for node in result.rows]
        assert values == [0.0, 1.0, None]
        assert all(isinstance(v, float) for v in values if v is not None)


class TestEndpointCatalog:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_query_root_field_matches_declared_graphql_query_name(self, endpoint_name: str) -> None:
        # The paginator reads payload["data"][graphql_query_name]. If the catalog's query name
        # drifts from the root field the query actually asks for, every page raises KeyError.
        query = QUERIES[endpoint_name]
        root_field = re.search(r"\)\s*\{\s*\n\s*(\w+)\(", query)
        assert root_field is not None, f"could not find a root field in the {endpoint_name} query"
        assert root_field.group(1) == _graphql_query_name(endpoint_name)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_filter_variable_is_declared_exactly_when_the_endpoint_is_incremental(self, endpoint_name: str) -> None:
        # The incremental cutoff rides in a $filter variable. Linear ignores variables a query
        # doesn't declare, so an incremental endpoint whose query omits $filter silently re-reads
        # the whole collection on every sync instead of failing.
        declares_filter = "$filter" in QUERIES[endpoint_name]
        assert declares_filter == bool(INCREMENTAL_FIELDS[endpoint_name])

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_query_selects_primary_key_and_partition_keys(self, endpoint_name: str) -> None:
        # A primary key or partition key that the query never selects lands as a missing column:
        # merges stop deduping and partitioning silently degrades.
        config = LINEAR_ENDPOINTS[endpoint_name]
        query = QUERIES[endpoint_name]
        for required in [config.primary_key, *(config.partition_keys or [])]:
            assert re.search(rf"^\s*{required}\s*$", query, re.MULTILINE), (
                f"{endpoint_name} query does not select {required}"
            )

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_root_field_includes_archived_records(self, endpoint_name: str) -> None:
        # Linear hides archived entities unless the connection asks for them, and it auto-archives
        # closed cycles, issues and projects. Without this argument a row silently leaves the table
        # once it is archived, so historical rows thin out over time instead of failing loudly.
        query = QUERIES[endpoint_name]
        root_args = re.search(r"\)\s*\{\s*\n\s*\w+\(([^)]*)\)", query)
        assert root_args is not None, f"could not find root field arguments in the {endpoint_name} query"
        assert "includeArchived: true" in root_args.group(1), (
            f"{endpoint_name} query does not pass includeArchived on its root connection"
        )

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_query_selects_archived_at(self, endpoint_name: str) -> None:
        # Archived rows now land in the same table as live ones, so without this column there is no
        # way to tell them apart downstream.
        assert re.search(r"^\s*archivedAt\s*$", QUERIES[endpoint_name], re.MULTILINE), (
            f"{endpoint_name} query does not select archivedAt"
        )


class TestRateLimitBackoff:
    @parameterized.expand(
        [
            ("delta_seconds", {"Retry-After": "30"}, 30.0),
            ("zero", {"Retry-After": "0"}, 0.0),
            ("fractional", {"Retry-After": "12.5"}, 12.5),
            ("missing", {}, None),
            ("http_date_unsupported", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
            ("non_numeric", {"Retry-After": "soon"}, None),
        ]
    )
    def test_parse_retry_after(self, _name: str, headers: dict[str, str], expected: float | None) -> None:
        assert _parse_retry_after(_make_rate_limited_response(headers)) == expected

    def test_429_carries_retry_after_into_exception(self) -> None:
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        result = _driver().run(
            "issues",
            always(ScriptedResponse(status=429, headers={"Retry-After": "0"}, body=b"<html>Rate limited</html>")),
        )

        assert isinstance(result.raised, LinearRetryableError)
        assert result.raised.retry_after == 0.0
        assert len(result.requests) == LINEAR_MAX_RETRY_ATTEMPTS


class TestLinearSource:
    def test_get_rows_threads_manager_through(self) -> None:
        result = _driver().run(
            "issues", [_page("issues", [{"id": "a"}], True, "cursor-a"), _page("issues", [{"id": "b"}])]
        )

        assert result.raised is None
        assert result.items == [[{"id": "a"}], [{"id": "b"}]]
        assert result.saved_states == [LinearResumeConfig(cursor="cursor-a")]


class TestLinearSourceNonRetryableErrors:
    @parameterized.expand(
        [
            # The OAuthMixin raises "Integration not found: <id>" when the linked integration was
            # deleted. The id varies, so matching must rely on the stable prefix.
            ("deleted_integration", "Integration not found: 165665"),
            ("auth_401", "401 Client Error: Unauthorized for url: https://api.linear.app/graphql"),
            ("forbidden_403", "403 Client Error: Forbidden for url: https://api.linear.app/graphql"),
            # NotImplementedError raised by OauthIntegration when the instance lacks Linear client id/secret.
            ("app_not_configured", "Linear app not configured"),
        ]
    )
    def test_non_retryable_errors_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = LinearSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("transient_500", "500 Server Error for url: https://api.linear.app/graphql"),
            ("rate_limited", "Linear: rate limited (429)"),
            ("graphql_error", "Linear GraphQL error: Something failed"),
            (
                "read_timeout",
                "Linear: transient network error - HTTPSConnectionPool(host='api.linear.app', port=443): Read timed out. (read timeout=60)",
            ),
        ]
    )
    def test_non_retryable_errors_does_not_match_transient(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = LinearSource().get_non_retryable_errors()
        # Transient/server errors must stay retryable so the pipeline backs off and retries.
        assert not any(key in observed_error for key in non_retryable_errors)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unauthorized_401", ScriptedResponse(status=401, json={}), "Linear rejected your connection"),
            (
                "authentication_error_400",
                ScriptedResponse(status=400, json={"errors": [{"extensions": {"code": "AUTHENTICATION_ERROR"}}]}),
                "Linear rejected your connection",
            ),
            ("forbidden_403", ScriptedResponse(status=403, json={}), "can't read this workspace"),
            ("server_error_503", ScriptedResponse(status=503, json={}), "Couldn't reach Linear"),
            (
                "unexpected_graphql_error",
                ScriptedResponse(status=400, json={"errors": [{"message": "boom"}]}),
                "Couldn't verify your Linear connection",
            ),
            ("network_error", requests.exceptions.ConnectionError("api.linear.app down"), "Couldn't reach Linear"),
        ]
    )
    def test_failures_return_user_facing_message(
        self, _name: str, outcome: ScriptedResponse | Exception, expected_message: str
    ) -> None:
        with scripted_network(always(outcome)) as network:
            valid, message = validate_credentials("tok")

        assert valid is False
        assert message is not None
        assert expected_message in message
        assert "api.linear.app" not in message
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_viewer_response_is_valid(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": {"viewer": {"id": "user-1"}}})]) as network:
            assert validate_credentials("tok") == (True, None)

        assert len(network.requests_log) == 1
