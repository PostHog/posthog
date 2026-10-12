import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh import (
    ACCOUNT_LOOKUP_FAILED,
    ACCOUNT_LOOKUP_MESSAGE,
    CODEFRESH_BASE_URL,
    CodefreshResumeConfig,
    _flatten,
    _resolve_account_id,
    _transform_row,
    codefresh_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    CodefreshEndpointConfig,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the codefresh module.
CODEFRESH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: CodefreshResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Wire a mock session; return (param_snapshots, header_snapshots) captured AT PREPARE TIME.

    ``request.params`` / ``request.headers`` are single dicts mutated in place across pages, so
    inspecting them after the run shows only the final state — snapshot a copy per request instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    header_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        header_snapshots.append(dict(request.headers or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, header_snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None, account_teams: Any = None):
    """Build the source response, stubbing the /team lookup the ``users`` path needs for its
    account id. Other endpoints never make that call, so the stub is inert for them."""
    session = mock.MagicMock()
    session.get.return_value = _response([{"account": "acc-1"}] if account_teams is None else account_teams)
    with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
        return codefresh_source(
            "token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager or _make_manager()
        )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_then_short_page_paginates_and_saves(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"p_{i}"} for i in range(100)]
        params, _headers = _wire(session, [_response(full_page), _response([{"id": "p_last"}])])
        manager = _make_manager()

        rows = _rows(_source("projects", manager))

        assert [r["id"] for r in rows] == [*(f"p_{i}" for i in range(100)), "p_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100
        # State saved exactly once, after the first (full) page is yielded, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CodefreshResumeConfig(offset=100)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _headers = _wire(session, [_response([{"id": "p_201"}])])
        manager = _make_manager(CodefreshResumeConfig(offset=200))

        rows = _rows(_source("projects", manager))

        assert rows == [{"id": "p_201"}]
        assert params[0]["offset"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_on_bare_array_endpoint_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unexpected envelope"})])

        # A 200 body that isn't a list means the response shape changed — fail loud instead of
        # syncing the stray object as a row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("projects"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_projects_variables_are_redacted(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "p1", "variables": [{"key": "TOKEN", "value": "secret"}]}])])

        rows = _rows(_source("projects"))

        assert rows == [{"id": "p1"}]


class TestPagePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_and_forwards_session_id(self, MockSession) -> None:
        session = MockSession.return_value
        params, headers = _wire(
            session,
            [
                _response(
                    {
                        "workflows": {"docs": [{"id": "b1"}, {"id": "b2"}]},
                        "pagination": {"sessionId": "sess-1", "nextPage": True},
                    }
                ),
                _response(
                    {
                        "workflows": {"docs": [{"id": "b3"}]},
                        "pagination": {"sessionId": "sess-1", "nextPage": False},
                    }
                ),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("builds", manager))

        assert [r["id"] for r in rows] == ["b1", "b2", "b3"]
        assert params[0] == {"limit": 100, "page": 1}
        assert params[1]["page"] == 2
        # The session cursor opened by page 1 must be pinned on page 2 so the snapshot is stable.
        assert "X-Pagination-Session-Id" not in headers[0]
        assert headers[1]["X-Pagination-Session-Id"] == "sess-1"
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CodefreshResumeConfig(page=2, session_id="sess-1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page_and_session(self, MockSession) -> None:
        session = MockSession.return_value
        params, headers = _wire(
            session,
            [_response({"workflows": {"docs": [{"id": "b9"}]}, "pagination": {"nextPage": False}})],
        )
        manager = _make_manager(CodefreshResumeConfig(page=3, session_id="sess-resume"))

        rows = _rows(_source("builds", manager))

        assert rows == [{"id": "b9"}]
        assert params[0]["page"] == 3
        assert headers[0]["X-Pagination-Session-Id"] == "sess-resume"


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


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
        session = mock.MagicMock()
        session.get.return_value = _FakeResponse(status)
        with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
            valid, error = validate_credentials("token", schema_name=schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert error is not None

    def test_users_schema_is_rejected_when_no_team_names_an_account(self) -> None:
        # A 200 from /team that names no account passes a status probe but fails the sync later,
        # so validation has to reject it rather than report the table as reachable.
        session = mock.MagicMock()
        session.get.return_value = _response([{"_id": "t1", "name": "users"}])
        with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
            valid, error = validate_credentials("token", schema_name="users")
        assert valid is False
        assert error == ACCOUNT_LOOKUP_MESSAGE

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_users_schema_reports_the_status_the_team_lookup_returned(self, _name: str, status: int) -> None:
        # A denied /team lookup is a credential answer, not an account answer, so the status
        # mapping must report it instead of the account-lookup message.
        denied = Response()
        denied.status_code = status
        denied._content = b"{}"
        denied.url = f"{CODEFRESH_BASE_URL}/team"
        session = mock.MagicMock()
        session.get.side_effect = [denied, _FakeResponse(status)]
        with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
            valid, error = validate_credentials("token", schema_name="users")
        assert valid is False
        assert error != ACCOUNT_LOOKUP_MESSAGE

    def test_connection_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
            valid, error = validate_credentials("token")
        assert valid is False
        assert error is not None


class TestAccountIdResolution:
    def _patched(self, body: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.return_value = _response(body)
        return session

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
        session = self._patched(body)
        with mock.patch(CODEFRESH_SESSION_PATCH, return_value=session):
            with pytest.raises(ValueError, match=ACCOUNT_LOOKUP_FAILED):
                _resolve_account_id("token")


class TestEnvelopeEndpointFailsLoudOnAMissingDataKey:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_body_without_the_docs_envelope_fails_loud(self, MockSession) -> None:
        # Codefresh does not document this response body. A shape we did not expect must stop the
        # sync instead of quietly syncing an empty table on every run.
        session = MockSession.return_value
        _wire(session, [_response([{"_id": "e1"}])])

        with pytest.raises(ValueError, match="matched nothing in the response"):
            _rows(_source("environments"))


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
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
