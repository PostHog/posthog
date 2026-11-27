from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import JSONResponseCursorPaginator
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.sprig._config import SprigSourceConfig
from products.warehouse_sources.sources.sprig.settings import ENDPOINTS, SPRIG_API_BASE_URL, SPRIG_ENDPOINTS
from products.warehouse_sources.sources.sprig.source import SprigSource
from products.warehouse_sources.sources.sprig.sprig import (
    SprigRedirectError,
    SprigResumeConfig,
    _format_incremental_value,
    get_resource,
    validate_credentials,
)


def _response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


def _run(script: Any, resume_state: SprigResumeConfig | None = None, endpoint: str = "Surveys") -> DriveResult:
    return SourceDriver(SprigSource(), SprigSourceConfig(api_key="key")).run(
        endpoint, script, resume_state=resume_state
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("none_passthrough", None, None),
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            ("date_value", date(2026, 3, 4), 1772582400000),
            ("int_passthrough", 1772582400000, 1772582400000),
            ("float_truncated", 1772582400000.9, 1772582400000),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094000),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_format(self, _label: str, value: Any, expected: Any) -> None:
        assert _format_incremental_value(value) == expected


class TestGetResource:
    @staticmethod
    def _params(resource: Any) -> dict[str, Any]:
        endpoint = cast(dict[str, Any], resource["endpoint"])
        return cast(dict[str, Any], endpoint["params"])

    @parameterized.expand(
        [
            ("Surveys", 1000),
            ("Responses", 1000),
            # The themes spec takes no `limit` param.
            ("Themes", None),
            ("Studies", 50),
            ("EventDefinitions", 50),
        ]
    )
    def test_resource_shape(self, endpoint: str, expected_limit: int | None) -> None:
        cfg = SPRIG_ENDPOINTS[endpoint]
        resource = get_resource(endpoint, should_use_incremental_field=False)
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = self._params(resource)

        assert resource["name"] == cfg.name
        assert resource["table_name"] == cfg.table_name
        assert resource["table_format"] == "delta"
        assert endpoint_config["path"] == cfg.path
        assert endpoint_config["data_selector"] == "data"
        assert params.get("limit") == expected_limit
        assert "start" not in params
        assert resource["write_disposition"] == "replace"

    @parameterized.expand([name for name in ENDPOINTS if SPRIG_ENDPOINTS[name].supports_incremental])
    def test_incremental_resource_sets_filter_and_merges(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        param = cast(dict[str, Any], self._params(resource)["start"])
        assert param["type"] == "incremental"
        assert param["cursor_path"] == "createdAt"
        assert param["convert"] is _format_incremental_value

    def test_full_refresh_only_endpoint_ignores_incremental_flag(self) -> None:
        resource = get_resource("Themes", should_use_incremental_field=True)

        assert resource["write_disposition"] == "replace"
        assert "start" not in self._params(resource)


class TestSprigCursorPaginator:
    def _paginator(self) -> JSONResponseCursorPaginator:
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")

    @parameterized.expand([("null_cursor", None), ("missing_cursor_key", "missing")])
    def test_update_state_terminal_page(self, _label: str, cursor_value: str | None) -> None:
        paginator = self._paginator()
        body: dict[str, Any] = {"data": [{"id": 1}]}
        if cursor_value != "missing":
            body["cursor"] = cursor_value
        paginator.update_state(_response(body))
        assert paginator.has_next_page is False


class TestSprigSource:
    def test_seeds_initial_paginator_state_from_saved_cursor(self) -> None:
        result = _run(
            [ScriptedResponse(json={"data": [{"id": 1}], "cursor": None})],
            resume_state=SprigResumeConfig(next_cursor="saved-cursor"),
        )

        assert result.requests[0].param("cursor") == "saved-cursor"

    @parameterized.expand(
        [
            ("Surveys", "/v1/surveys", "1000"),
            ("Themes", "/v1/themes", None),
            ("Studies", "/v2/studies", "50"),
            ("EventDefinitions", "/v2/events", "50"),
        ]
    )
    def test_resume_hook_saves_state_after_batch(self, endpoint: str, path: str, limit: str | None) -> None:
        result = _run(
            [
                ScriptedResponse(json={"data": [{"id": 1}], "cursor": "next-1"}),
                ScriptedResponse(json={"data": [{"id": 2}], "cursor": None}),
            ],
            endpoint=endpoint,
        )

        assert result.paths == [path, path]
        assert result.params("limit") == [limit, limit]
        assert result.params("cursor") == [None, "next-1"]
        assert result.rows == [{"id": 1}, {"id": 2}]
        # The terminal page has no cursor, so nothing is saved for it.
        assert result.saved_states == [SprigResumeConfig(next_cursor="next-1")]

    @parameterized.expand(
        [
            ("Surveys", "Bearer key"),
            ("Studies", "API-Key key"),
            ("EventDefinitions", "API-Key key"),
        ]
    )
    def test_auth_scheme_matches_api_version(self, endpoint: str, expected_authorization: str) -> None:
        result = _run([ScriptedResponse(json={"data": [{"id": 1}], "cursor": None})], endpoint=endpoint)

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == expected_authorization

    @parameterized.expand([("Studies", "createdAt"), ("EventDefinitions", None)])
    def test_study_api_tables_are_full_refresh_with_no_assumed_order(
        self, endpoint: str, partition_key: str | None
    ) -> None:
        result = _run([ScriptedResponse(json={"data": [{"id": 1}], "cursor": None})], endpoint=endpoint)

        assert result.response is not None
        assert result.response.sort_mode is None
        assert result.response.partition_keys == ([partition_key] if partition_key else None)


class TestStudyFanout:
    @parameterized.expand(
        [
            ("Questions", "questions", "id", None),
            ("Invitations", "invitations", "code", "SURVEY"),
        ]
    )
    def test_walks_every_study_and_tags_rows_with_study_id(
        self, endpoint: str, child_segment: str, row_key: str, expected_parent_type: str | None
    ) -> None:
        result = _run(
            route(
                {
                    f"/v2/studies/s1/{child_segment}": [
                        ScriptedResponse(json={"data": [{row_key: "a"}], "cursor": "c1"}),
                        ScriptedResponse(json={"data": [{row_key: "b"}], "cursor": None}),
                    ],
                    f"/v2/studies/s2/{child_segment}": [
                        ScriptedResponse(json={"data": [{row_key: "a"}], "cursor": None}),
                    ],
                    "/v2/studies": [
                        ScriptedResponse(json={"data": [{"id": "s1"}], "cursor": "p1"}),
                        ScriptedResponse(json={"data": [{"id": "s2"}], "cursor": None}),
                    ],
                }
            ),
            endpoint=endpoint,
        )

        assert result.raised is None
        assert sorted((row["study_id"], row[row_key]) for row in result.rows) == [("s1", "a"), ("s1", "b"), ("s2", "a")]
        assert all("_Studies_id" not in row for row in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == ["study_id", row_key]
        assert result.saved_states == []

        parent_requests = [r for r in result.requests if r.path == "/v2/studies"]
        child_requests = [r for r in result.requests if r.path.endswith(child_segment)]
        assert [r.param("type") for r in parent_requests] == [expected_parent_type] * 2
        assert [r.param("cursor") for r in parent_requests] == [None, "p1"]
        assert [r.param("cursor") for r in child_requests] == [None, "c1", None]
        assert all(r.param("limit") == "50" for r in result.requests)
        assert all(r.headers["authorization"] == "API-Key key" for r in result.requests)

    @parameterized.expand(
        [
            ("questions_study_deleted", "Questions", "questions", 404),
            ("questions_unrepresentable_study", "Questions", "questions", 409),
            ("invitations_study_deleted", "Invitations", "invitations", 404),
            ("invitations_not_a_survey", "Invitations", "invitations", 422),
        ]
    )
    def test_documented_per_study_error_skips_that_study(
        self, _label: str, endpoint: str, child_segment: str, status: int
    ) -> None:
        result = _run(
            route(
                {
                    f"/v2/studies/bad/{child_segment}": [
                        ScriptedResponse(status=status, json={"code": "ERROR", "message": "skipped"})
                    ],
                    f"/v2/studies/good/{child_segment}": [
                        ScriptedResponse(json={"data": [{"id": "q1", "code": "q1"}], "cursor": None})
                    ],
                    "/v2/studies": [ScriptedResponse(json={"data": [{"id": "bad"}, {"id": "good"}], "cursor": None})],
                }
            ),
            endpoint=endpoint,
        )

        assert result.raised is None
        assert [row["study_id"] for row in result.rows] == ["good"]

    @parameterized.expand(
        [("questions_forbidden", "Questions", "questions"), ("invitations_forbidden", "Invitations", "invitations")]
    )
    def test_forbidden_child_fails_the_table(self, _label: str, endpoint: str, child_segment: str) -> None:
        result = _run(
            route(
                {
                    f"/v2/studies/s1/{child_segment}": [ScriptedResponse(status=403, json={})],
                    "/v2/studies": [ScriptedResponse(json={"data": [{"id": "s1"}], "cursor": None})],
                }
            ),
            endpoint=endpoint,
        )

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error: Forbidden for url: https://api.sprig.com" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_errors_raise(self, _label: str, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            with pytest.raises(HTTPError):
                validate_credentials("key")


class TestRedirectsRefused:
    # A redirected request lands on a host that answers 403 with a bot challenge, which must not
    # be read as an auth failure. Redirects are refused so the token never leaves the API host.
    API_URL = f"{SPRIG_API_BASE_URL}/v1/surveys"
    TARGET_URL = "https://sprig.com/v1/surveys"

    @parameterized.expand([("moved_permanently", 301), ("found", 302)])
    def test_sync_refuses_redirect_and_keeps_token_on_api_host(self, _label: str, status: int) -> None:
        result = _run(
            [
                ScriptedResponse(status=status, headers={"Location": self.TARGET_URL}),
                ScriptedResponse(status=403),
            ]
        )

        assert isinstance(result.raised, ValueError)
        assert "Unexpected redirect" in str(result.raised) and "refusing to follow" in str(result.raised)
        assert [request.origin for request in result.requests] == [SPRIG_API_BASE_URL]
        assert result.requests[0].headers["authorization"] == "Bearer key"

    def test_validate_credentials_refuses_redirect_instead_of_reporting_a_valid_key(self) -> None:
        script = [
            ScriptedResponse(status=302, headers={"Location": self.TARGET_URL}),
            ScriptedResponse(status=403),
        ]
        with scripted_network(script) as network:
            with pytest.raises(SprigRedirectError, match="redirected the API request to sprig.com"):
                validate_credentials("key")

        assert [request.origin for request in network.requests_log] == [SPRIG_API_BASE_URL]
