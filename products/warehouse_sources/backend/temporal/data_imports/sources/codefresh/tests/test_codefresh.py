from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh import (
    ACCOUNT_LOOKUP_FAILED,
    ACCOUNT_LOOKUP_MESSAGE,
    CodefreshResumeConfig,
    _flatten,
    _resolve_account_id,
    _transform_row,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    CodefreshEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source import CodefreshSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codefresh import (
    CodefreshSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CodefreshSource(), CodefreshSourceConfig(api_key="token"))


class TestFlatten:
    def test_lifts_nested_object_to_top_level(self) -> None:
        item = {"metadata": {"id": "p1", "name": "build-and-test"}, "spec": {"steps": {}}}
        result = _flatten(item, "metadata")
        assert result["id"] == "p1"
        assert result["name"] == "build-and-test"
        assert result["spec"] == {"steps": {}}
        assert "metadata" not in result


class TestTransformRow:
    @parameterized.expand(
        [
            (
                "top_level_key",
                ["variables"],
                {"id": "p1", "variables": [{"key": "TOKEN", "value": "secret"}]},
                {"id": "p1"},
            ),
            (
                "nested_dotted_key",
                ["spec.variables"],
                {"id": "p1", "spec": {"steps": {}, "variables": [{"key": "TOKEN", "value": "secret"}]}},
                {"id": "p1", "spec": {"steps": {}}},
            ),
            (
                "nested_path_absent_is_noop",
                ["spec.variables"],
                {"id": "p1", "spec": {"steps": {}}},
                {"id": "p1", "spec": {"steps": {}}},
            ),
            (
                "nested_parent_not_a_dict_is_noop",
                ["spec.variables"],
                {"id": "p1", "spec": None},
                {"id": "p1", "spec": None},
            ),
        ]
    )
    def test_redacts_configured_keys(
        self, _name: str, redact_keys: list[str], item: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        config = CodefreshEndpointConfig(
            name="projects", path="/projects", pagination="offset", redact_keys=redact_keys
        )
        assert _transform_row(item, config) == expected

    def test_redaction_does_not_mutate_source_item(self) -> None:
        config = CodefreshEndpointConfig(
            name="pipelines", path="/pipelines", pagination="offset", redact_keys=["spec.variables"]
        )
        item = {"id": "p1", "spec": {"variables": [{"key": "TOKEN", "value": "secret"}]}}
        _transform_row(item, config)
        assert item["spec"] == {"variables": [{"key": "TOKEN", "value": "secret"}]}

    def test_no_redact_keys_is_passthrough(self) -> None:
        config = CodefreshEndpointConfig(name="builds", path="/workflow", pagination="page")
        row = _transform_row({"id": "b1", "variables": ["x"]}, config)
        assert row == {"id": "b1", "variables": ["x"]}

    @parameterized.expand(
        [
            ("projects", "variables"),
            ("pipelines", "spec.variables"),
            ("triggers", "event-data.endpoint"),
            ("triggers", "event-data.secret"),
            ("users", "inviteUrl"),
        ]
    )
    def test_endpoint_redacts_secret_bearing_variables(self, endpoint: str, redacted_key: str) -> None:
        # These endpoints expose plaintext config/CI variables, webhook secrets, or an invite URL
        # that grants account access; the configured source must strip them.
        assert redacted_key in CODEFRESH_ENDPOINTS[endpoint].redact_keys


class TestOffsetPagination:
    def test_full_page_then_short_page_paginates_and_saves(self) -> None:
        full_page = [{"id": f"p_{i}"} for i in range(100)]
        result = _driver().run(
            "projects", [ScriptedResponse(json=full_page), ScriptedResponse(json=[{"id": "p_last"}])]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(f"p_{i}" for i in range(100)), "p_last"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        # State saved exactly once, after the first (full) page is yielded, pointing at the next offset.
        assert result.saved_states == [CodefreshResumeConfig(offset=100)]

    def test_resume_starts_from_saved_offset(self) -> None:
        result = _driver().run(
            "projects", [ScriptedResponse(json=[{"id": "p_201"}])], resume_state=CodefreshResumeConfig(offset=200)
        )

        assert result.raised is None
        assert result.rows == [{"id": "p_201"}]
        assert result.params("offset") == ["200"]

    def test_non_list_body_on_bare_array_endpoint_fails_loud(self) -> None:
        result = _driver().run("projects", [ScriptedResponse(json={"error": "unexpected envelope"})])

        # A 200 body that isn't a list means the response shape changed — fail loud instead of
        # syncing the stray object as a row.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_projects_variables_are_redacted(self) -> None:
        result = _driver().run(
            "projects", [ScriptedResponse(json=[{"id": "p1", "variables": [{"key": "TOKEN", "value": "secret"}]}])]
        )

        assert result.raised is None
        assert result.rows == [{"id": "p1"}]


class TestPagePagination:
    def test_follows_next_page_and_forwards_session_id(self) -> None:
        result = _driver().run(
            "builds",
            [
                ScriptedResponse(
                    json={
                        "workflows": {"docs": [{"id": "b1"}, {"id": "b2"}]},
                        "pagination": {"sessionId": "sess-1", "nextPage": True},
                    }
                ),
                ScriptedResponse(
                    json={
                        "workflows": {"docs": [{"id": "b3"}]},
                        "pagination": {"sessionId": "sess-1", "nextPage": False},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["b1", "b2", "b3"]
        assert result.queries[0] == {"limit": ("100",), "page": ("1",)}
        assert result.params("page") == ["1", "2"]
        # The session cursor opened by page 1 must be pinned on page 2 so the snapshot is stable.
        assert "x-pagination-session-id" not in result.requests[0].headers
        assert result.requests[1].headers["x-pagination-session-id"] == "sess-1"
        assert result.saved_states == [CodefreshResumeConfig(page=2, session_id="sess-1")]

    def test_resume_starts_from_saved_page_and_session(self) -> None:
        result = _driver().run(
            "builds",
            [ScriptedResponse(json={"workflows": {"docs": [{"id": "b9"}]}, "pagination": {"nextPage": False}})],
            resume_state=CodefreshResumeConfig(page=3, session_id="sess-resume"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "b9"}]
        assert result.params("page") == ["3"]
        assert result.requests[0].headers["x-pagination-session-id"] == "sess-resume"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_is_rejected", 403, "projects", False),
            ("rate_limited", 429, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            valid, error = validate_credentials("token", schema_name=schema_name)

        assert valid is expected_valid
        assert network.requests_log[0].path == "/api/projects"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "token"
        if not expected_valid:
            assert error is not None

    def test_users_schema_is_rejected_when_no_team_names_an_account(self) -> None:
        # A 200 from /team that names no account passes a status probe but fails the sync later,
        # so validation has to reject it rather than report the table as reachable.
        with scripted_network([ScriptedResponse(json=[{"_id": "t1", "name": "users"}])]) as network:
            valid, error = validate_credentials("token", schema_name="users")

        assert valid is False
        assert error == ACCOUNT_LOOKUP_MESSAGE
        assert [request.path for request in network.requests_log] == ["/api/team"]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_users_schema_reports_the_status_the_team_lookup_returned(self, _name: str, status: int) -> None:
        # A denied /team lookup is a credential answer, not an account answer, so the status
        # mapping must report it instead of the account-lookup message.
        with scripted_network([ScriptedResponse(status=status), ScriptedResponse(status=status)]) as network:
            valid, error = validate_credentials("token", schema_name="users")

        assert valid is False
        assert error != ACCOUNT_LOOKUP_MESSAGE
        assert [request.path for request in network.requests_log] == ["/api/team", "/api/team"]
        assert network.requests_log[1].param("limit") == "1"

    def test_connection_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, error = validate_credentials("token")

        assert valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/projects"}


class TestAccountIdResolution:
    @parameterized.expand(
        [
            ("no_teams", []),
            ("team_without_account", [{"_id": "t1", "name": "users"}]),
            ("unexpected_envelope", {"docs": [{"account": "acc-7"}]}),
        ]
    )
    def test_unresolvable_account_raises_the_curated_error(self, _name: str, body: Any) -> None:
        # The message is what the user reads, because the source maps this prefix to an explanation
        # in get_non_retryable_errors.
        with scripted_network([ScriptedResponse(json=body)]) as network:
            with pytest.raises(ValueError, match=ACCOUNT_LOOKUP_FAILED):
                _resolve_account_id("token")

        assert [request.path for request in network.requests_log] == ["/api/team"]


class TestEnvelopeEndpointFailsLoudOnAMissingDataKey:
    def test_body_without_the_docs_envelope_fails_loud(self) -> None:
        # Codefresh does not document this response body. A shape we did not expect must stop the
        # sync instead of quietly syncing an empty table on every run.
        result = _driver().run("environments", [ScriptedResponse(json=[{"_id": "e1"}])])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing in the response" in str(result.raised)


class TestCodefreshSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["id"], None),
            ("pipelines", ["id"], None),
            ("builds", ["id"], "created"),
            ("images", ["id"], "created"),
            ("triggers", ["event", "pipeline"], None),
            ("step_types", ["id"], None),
            ("environments", ["_id"], None),
            ("teams", ["_id"], None),
            ("users", ["_id"], None),
        ]
    )
    def test_source_response_primary_keys_and_partition(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        if endpoint == "users":
            script = [ScriptedResponse(json=[{"account": "acc-1"}]), ScriptedResponse(json=[])]
        elif endpoint == "builds":
            script = [ScriptedResponse(json={"workflows": {"docs": []}, "pagination": {"nextPage": False}})]
        elif endpoint in {"pipelines", "environments"}:
            script = [ScriptedResponse(json={"docs": []})]
        else:
            script = [ScriptedResponse(json=[])]

        result = _driver().run(endpoint, script)
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
