import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten import (
    BasetenResumeConfig,
    baseten_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the baseten module.
BASETEN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.baseten.co/v1/test"
    return resp


def _make_manager(resume_state: BasetenResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return snapshots of each request's url/params/auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "bearer_token": getattr(request.auth, "token", None),
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    endpoint: str, manager: mock.MagicMock, session: mock.MagicMock, responses: list[Response]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots = _wire(session, responses)
    rows = _rows(baseten_source("test-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager))
    return rows, snapshots


class TestTopLevelEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_under_data_key(self, MockSession) -> None:
        session = MockSession.return_value
        rows, snapshots = _run(
            "models", _make_manager(), session, [_response({"models": [{"id": "m1"}, {"id": "m2"}]})]
        )
        assert rows == [{"id": "m1"}, {"id": "m2"}]
        assert snapshots[0]["url"] == "https://api.baseten.co/v1/models"
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_goes_through_framework_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        _, snapshots = _run("models", _make_manager(), session, [_response({"models": [{"id": "m1"}]})])
        assert snapshots[0]["bearer_token"] == "test-key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_array_yields_nothing(self, MockSession) -> None:
        rows, _ = _run("models", _make_manager(), MockSession.return_value, [_response({"models": []})])
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_nothing(self, MockSession) -> None:
        # The Baseten client has always treated a missing data key as zero rows, not an error.
        rows, _ = _run("models", _make_manager(), MockSession.return_value, [_response({"unexpected": True})])
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_instance_type_prices_flattened(self, MockSession) -> None:
        body = {
            "instance_types": [
                # Nested object lifts into the root; root-level siblings win on collision.
                {"instance_type": {"id": "gpu-1", "name": "A100", "price": 999}, "price": 0.5},
                # Rows without the nested key pass through untouched.
                {"id": "plain"},
            ]
        }
        rows, _ = _run("instance_type_prices", _make_manager(), MockSession.return_value, [_response(body)])
        assert rows == [{"id": "gpu-1", "name": "A100", "price": 0.5}, {"id": "plain"}]


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_until_has_more_false_and_saves_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        manager = _make_manager()
        responses = [
            _response({"items": [{"user_id": "u1"}], "pagination": {"has_more": True, "cursor": "c1"}}),
            _response({"items": [{"user_id": "u2"}], "pagination": {"has_more": True, "cursor": "c2"}}),
            _response({"items": [{"user_id": "u3"}], "pagination": {"has_more": False, "cursor": None}}),
        ]
        rows, snapshots = _run("users", manager, session, responses)

        assert rows == [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}]
        # First request has no cursor; later requests carry the prior page's cursor.
        assert [s["params"].get("cursor") for s in snapshots] == [None, "c1", "c2"]
        assert all(s["params"]["limit"] == 100 for s in snapshots)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [BasetenResumeConfig(cursor="c1"), BasetenResumeConfig(cursor="c2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_does_not_save(self, MockSession) -> None:
        manager = _make_manager()
        _run(
            "users",
            manager,
            MockSession.return_value,
            [_response({"items": [{"user_id": "u1"}], "pagination": {"has_more": False}})],
        )
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_has_more_false_stops_even_if_cursor_echoed(self, MockSession) -> None:
        # `has_more` is authoritative — a cursor echoed on the terminal page must not cause a loop.
        session = MockSession.return_value
        rows, _ = _run(
            "users",
            _make_manager(),
            session,
            [_response({"items": [{"user_id": "u1"}], "pagination": {"has_more": False, "cursor": "stale"}})],
        )
        assert rows == [{"user_id": "u1"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_saved_cursor(self, MockSession) -> None:
        manager = _make_manager(BasetenResumeConfig(cursor="resumed-cursor"))
        _, snapshots = _run(
            "users", manager, MockSession.return_value, [_response({"items": [{"user_id": "u9"}], "pagination": {}})]
        )
        assert snapshots[0]["params"].get("cursor") == "resumed-cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_load_state_when_cannot_resume(self, MockSession) -> None:
        manager = _make_manager()
        _run("users", manager, MockSession.return_value, [_response({"items": [], "pagination": {}})])
        manager.load_state.assert_not_called()


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_parent_id_and_yields_per_parent(self, MockSession) -> None:
        manager = _make_manager()
        responses = [
            _response({"models": [{"id": "m1"}, {"id": "m2"}]}),  # parent list
            _response({"deployments": [{"id": "d1"}]}),  # m1 children
            _response({"deployments": [{"id": "d2"}]}),  # m2 children
        ]
        rows, snapshots = _run("deployments", manager, MockSession.return_value, responses)

        assert rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]
        assert snapshots[1]["url"] == "https://api.baseten.co/v1/models/m1/deployments"
        assert snapshots[2]["url"] == "https://api.baseten.co/v1/models/m2/deployments"
        # The resolve param binds into the path, not the query string.
        assert "model_id" not in snapshots[1]["params"]
        # A checkpoint marking m1 complete is saved before m2 is processed.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert (
            BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            )
            in saved
        )
        # Every checkpoint stays parseable as the resume dataclass (cursor/parent_id untouched).
        assert all(s.cursor is None and s.parent_id is None and isinstance(s.fanout_state, dict) for s in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_composite_key_column_present_for_environments(self, MockSession) -> None:
        responses = [
            _response({"models": [{"id": "m1"}]}),
            _response({"environments": [{"name": "production"}]}),
        ]
        rows, _ = _run("model_environments", _make_manager(), MockSession.return_value, responses)
        # model_id is injected so [model_id, name] stays unique table-wide.
        assert rows == [{"name": "production", "model_id": "m1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_404_child_is_skipped(self, MockSession) -> None:
        responses = [
            _response({"models": [{"id": "gone"}, {"id": "m2"}]}),
            _response({"code": "NOT_FOUND"}, status_code=404),  # parent deleted mid-sync
            _response({"deployments": [{"id": "d2"}]}),
        ]
        rows, _ = _run("deployments", _make_manager(), MockSession.return_value, responses)
        assert rows == [{"id": "d2", "model_id": "m2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_parent_without_id_is_skipped(self, MockSession) -> None:
        responses = [
            _response({"models": [{"id": "m1"}, {"name": "orphan"}]}),  # second parent has no id
            _response({"deployments": [{"id": "d1"}]}),  # only m1's children are fetched
        ]
        rows, snapshots = _run("deployments", _make_manager(), MockSession.return_value, responses)
        assert rows == [{"id": "d1", "model_id": "m1"}]
        # The id-less parent must not produce a request against a stringified "None" id.
        assert not any("/models/None/" in s["url"] for s in snapshots)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_parents(self, MockSession) -> None:
        manager = _make_manager(
            BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            )
        )
        responses = [
            _response({"models": [{"id": "m1"}, {"id": "m2"}]}),
            _response({"deployments": [{"id": "d2"}]}),  # only m2 is fetched
        ]
        rows, snapshots = _run("deployments", manager, MockSession.return_value, responses)
        assert rows == [{"id": "d2", "model_id": "m2"}]
        child_urls = [s["url"] for s in snapshots if s["url"].endswith("/deployments") and "/models/" in s["url"]]
        assert child_urls == ["https://api.baseten.co/v1/models/m2/deployments"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_parent_id_state_restarts_fan_out(self, MockSession) -> None:
        # Pre-migration states bookmarked the next parent id; they still parse but the fan-out
        # restarts from the top (full-refresh tables, so re-appending is bounded).
        manager = _make_manager(BasetenResumeConfig(parent_id="m2"))
        responses = [
            _response({"models": [{"id": "m1"}, {"id": "m2"}]}),
            _response({"deployments": [{"id": "d1"}]}),
            _response({"deployments": [{"id": "d2"}]}),
        ]
        rows, _ = _run("deployments", manager, MockSession.return_value, responses)
        assert rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(("status", "expected"), [(200, True), (403, False), (401, False), (500, False)])
    def test_status_maps_to_bool(self, status: int, expected: bool) -> None:
        with mock.patch(BASETEN_SESSION_PATCH) as mock_factory:
            session = mock_factory.return_value
            session.get.return_value = _response({}, status_code=status)
            assert validate_credentials("key") is expected
            _, kwargs = session.get.call_args
            assert kwargs["headers"]["Authorization"] == "Bearer key"

    def test_network_error_is_false(self) -> None:
        with mock.patch(BASETEN_SESSION_PATCH) as mock_factory:
            mock_factory.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partition_and_primary_keys_match_config(self, MockSession, endpoint: str) -> None:
        config = BASETEN_ENDPOINTS[endpoint]
        response = baseten_source("k", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_items_is_lazy(self, MockSession) -> None:
        # Building the SourceResponse must not perform any I/O; requests only fire on iteration.
        session = MockSession.return_value
        session.headers = {}
        response = baseten_source("k", "deployments", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert callable(response.items)
        session.send.assert_not_called()
