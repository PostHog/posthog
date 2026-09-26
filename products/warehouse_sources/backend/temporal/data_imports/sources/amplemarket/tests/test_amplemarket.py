import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.amplemarket import (
    AmplemarketResumeConfig,
    amplemarket_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.settings import (
    AMPLEMARKET_ENDPOINTS,
    BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the amplemarket module.
AMPLEMARKET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.amplemarket.make_tracked_session"
)


def _response(data_key: str, items: list[dict[str, Any]], next_href: str | None, url: str) -> Response:
    body: dict[str, Any] = {data_key: items}
    if next_href is not None:
        body["_links"] = {"next": {"href": next_href}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    # The paginator resolves relative next hrefs against the response URL.
    resp.url = url
    return resp


def _make_manager(resume_state: AmplemarketResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request AT PREPARE TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them
    after the run shows only the final state — snapshot a copy when each request is prepared.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return amplemarket_source("api-key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(AMPLEMARKET_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("api-key") is expected

    @mock.patch(AMPLEMARKET_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("api-key") is False

    @mock.patch(AMPLEMARKET_SESSION_PATCH)
    def test_probes_account_info_with_bearer_token(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("api-key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.amplemarket.com/account-info"
        assert call.kwargs["headers"]["Authorization"] == "Bearer api-key"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_relative_next_link(self, MockSession):
        # Amplemarket returns HAL-style relative next hrefs with bracketed cursor params; the
        # paginator must resolve them against the base URL and drop the original params.
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response(
                    "sequences",
                    [{"id": "a"}, {"id": "b"}],
                    "/sequences?page[after]=b&page[size]=20",
                    f"{BASE_URL}/sequences",
                ),
                _response("sequences", [{"id": "c"}], None, f"{BASE_URL}/sequences?page[after]=b&page[size]=20"),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("sequences", manager))

        assert [row["id"] for row in rows] == ["a", "b", "c"]
        assert requests_seen[0]["url"] == f"{BASE_URL}/sequences"
        assert requests_seen[0]["params"] == {}
        assert requests_seen[1]["url"] == f"{BASE_URL}/sequences?page[after]=b&page[size]=20"
        assert requests_seen[1]["params"] == {}
        # State is saved only while a next page exists, with the resolved absolute URL.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AmplemarketResumeConfig(
            next_url=f"{BASE_URL}/sequences?page[after]=b&page[size]=20"
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_bearer_auth(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response("users", [{"id": "u1"}], None, f"{BASE_URL}/users")])

        _rows(_source("users", _make_manager()))

        auth = requests_seen[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "api-key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        resume_url = f"{BASE_URL}/sequences?page[after]=x&page[size]=20"
        requests_seen = _wire(session, [_response("sequences", [{"id": "y"}], None, resume_url)])

        manager = _make_manager(AmplemarketResumeConfig(next_url=resume_url))
        rows = _rows(_source("sequences", manager))

        assert [row["id"] for row in rows] == ["y"]
        assert requests_seen[0]["url"] == resume_url
        assert requests_seen[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_without_checkpoint(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response("calls", [], None, f"{BASE_URL}/calls")])

        manager = _make_manager()
        rows = _rows(_source("calls", manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestTasksFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tasks_are_fetched_per_user(self, MockSession):
        # /tasks requires a user_id filter, so the fan-out binds each parent user's id into the
        # child path and pages each user's tasks through their own next-link chain.
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response("users", [{"id": "u1"}, {"id": "u2"}], None, f"{BASE_URL}/users"),
                _response(
                    "tasks",
                    [{"id": "t1", "user_id": "u1"}],
                    "/tasks?user_id=u1&page[after]=t1",
                    f"{BASE_URL}/tasks?user_id=u1",
                ),
                _response(
                    "tasks",
                    [{"id": "t2", "user_id": "u1"}],
                    None,
                    f"{BASE_URL}/tasks?user_id=u1&page[after]=t1",
                ),
                _response("tasks", [{"id": "t3", "user_id": "u2"}], None, f"{BASE_URL}/tasks?user_id=u2"),
            ],
        )

        rows = _rows(_source("tasks", _make_manager()))

        assert [row["id"] for row in rows] == ["t1", "t2", "t3"]
        task_urls = [req["url"] for req in requests_seen if "/tasks" in (req["url"] or "")]
        assert task_urls == [
            f"{BASE_URL}/tasks?user_id=u1",
            f"{BASE_URL}/tasks?user_id=u1&page[after]=t1",
            f"{BASE_URL}/tasks?user_id=u2",
        ]


class TestEndpointSettings:
    @pytest.mark.parametrize("config", AMPLEMARKET_ENDPOINTS.values(), ids=AMPLEMARKET_ENDPOINTS.keys())
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"start_date", "created_at", "date_added"}
