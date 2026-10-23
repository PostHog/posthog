from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.braintrust import (
    BraintrustResumeConfig,
    braintrust_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.source import BraintrustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintrust import (
    BraintrustSourceConfig,
)

API_URL = "https://api.braintrust.dev"
HOST_CHECK = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid"


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as mock, patch(HOST_CHECK, return_value=(True, None)):
        yield mock


def make_config(api_url: str = API_URL, api_key: str = "fake-braintrust-key") -> BraintrustSourceConfig:
    return BraintrustSourceConfig(api_key=api_key, api_url=api_url)


def make_manager(cursor: str | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = cursor is not None
    manager.load_state.return_value = BraintrustResumeConfig(cursor=cursor) if cursor else None
    return manager


def make_driver(config: BraintrustSourceConfig | None = None) -> SourceDriver:
    return SourceDriver(BraintrustSource(), config or make_config())


@pytest.mark.parametrize(
    ("table", "path"),
    [
        ("projects", "project"),
        ("experiments", "experiment"),
        ("datasets", "dataset"),
        ("prompts", "prompt"),
        ("functions", "function"),
        ("users", "user"),
    ],
)
def test_pagination_auth_and_checkpoints(http: responses.RequestsMock, table: str, path: str) -> None:
    url = f"{API_URL}/v1/{path}"
    http.get(url, json={"objects": [{"id": "new"}, {"id": "middle"}]})
    http.get(url, json={"objects": [{"id": "old"}]})
    http.get(url, json={"objects": []})
    manager = make_manager()
    result = braintrust_source(make_config(), table, 123, "job", manager)
    pages = iter(cast(Iterable[Any], result.items()))
    assert next(pages) == [{"id": "new"}, {"id": "middle"}]
    assert list(pages) == [[{"id": "old"}]]
    assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["middle", "old"]
    assert [parse_qs(urlsplit(call.request.url).query) for call in http.calls] == [
        {"limit": ["100"]},
        {"limit": ["100"], "starting_after": ["middle"]},
        {"limit": ["100"], "starting_after": ["old"]},
    ]
    assert all(call.request.headers["Authorization"] == "Bearer fake-braintrust-key" for call in http.calls)
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once_with()


EVENT_TABLES = [
    ("project_logs", "project", "project_logs/{}/fetch", "project_id"),
    ("experiment_events", "experiment", "experiment/{}/fetch", "experiment_id"),
    ("dataset_events", "dataset", "dataset/{}/fetch", "dataset_id"),
]


def event_script(parent_path: str, child_path: str, parent_key: str) -> Any:
    return route(
        {
            f"/v1/{parent_path}": [
                ScriptedResponse(json={"objects": [{"id": "p1"}, {"id": "p2"}]}),
                ScriptedResponse(json={"objects": []}),
            ],
            f"/v1/{child_path.format('p1')}": [
                ScriptedResponse(
                    json={
                        "events": [{"id": "a", parent_key: "p1", "_xact_id": "3"}, {"id": "b", parent_key: "p1"}],
                        "cursor": "c1",
                    }
                ),
                ScriptedResponse(
                    json={
                        "events": [{"id": "a", parent_key: "p1", "_xact_id": "1"}, {"id": "c", parent_key: "p1"}],
                        "cursor": "c2",
                    }
                ),
                ScriptedResponse(json={"events": []}),
            ],
            f"/v1/{child_path.format('p2')}": [ScriptedResponse(json={"events": [{"id": "a", parent_key: "p2"}]})],
        }
    )


@pytest.mark.parametrize(("table", "parent_path", "child_path", "parent_key"), EVENT_TABLES)
def test_event_fanout_pages_by_body_cursor_and_drops_outdated_versions(
    table: str, parent_path: str, child_path: str, parent_key: str
) -> None:
    result = make_driver().run(table, event_script(parent_path, child_path, parent_key))
    assert result.raised is None
    assert [(row[parent_key], row["id"], row.get("_xact_id")) for row in result.rows] == [
        ("p1", "a", "3"),
        ("p1", "b", None),
        ("p1", "c", None),
        ("p2", "a", None),
    ]
    p1_requests = [request for request in result.requests if request.path == f"/v1/{child_path.format('p1')}"]
    assert [request.method for request in p1_requests] == ["POST"] * 3
    assert [request.json() for request in p1_requests] == [
        {"limit": 100},
        {"limit": 100, "cursor": "c1"},
        {"limit": 100, "cursor": "c2"},
    ]
    assert result.response is not None
    assert result.response.primary_keys == [parent_key, "id"]


def test_event_fanout_resumes_from_saved_parent_cursor() -> None:
    first = make_driver().run("project_logs", event_script("project", "project_logs/{}/fetch", "project_id"))
    assert first.raised is None
    mid_parent = next(
        state for state in first.saved_states if state.fanout and (state.fanout.get("child_state") or {}).get("cursor")
    )
    resumed = make_driver().run(
        "project_logs",
        route(
            {
                "/v1/project": [
                    ScriptedResponse(json={"objects": [{"id": "p1"}, {"id": "p2"}]}),
                    ScriptedResponse(json={"objects": []}),
                ],
                "/v1/project_logs/p1/fetch": [
                    ScriptedResponse(json={"events": [{"id": "c", "project_id": "p1"}]}),
                ],
                "/v1/project_logs/p2/fetch": [ScriptedResponse(json={"events": []})],
            }
        ),
        resume_state=mid_parent,
    )
    assert resumed.raised is None
    p1_bodies = [request.json() for request in resumed.requests if request.path == "/v1/project_logs/p1/fetch"]
    assert p1_bodies == [{"limit": 100, "cursor": "c1"}]
    assert [row["id"] for row in resumed.rows] == ["c"]


@pytest.mark.parametrize("cursor", [None, "saved"])
def test_empty_page_and_resume(cursor: str | None) -> None:
    result = make_driver().run(
        "projects",
        [ScriptedResponse(json={"objects": []})],
        resume_state=BraintrustResumeConfig(cursor=cursor) if cursor else None,
    )
    assert result.raised is None
    assert result.rows == []
    expected = {"limit": ("100",)}
    if cursor:
        expected["starting_after"] = (cursor,)
    assert result.queries == [expected]
    assert result.saved_states == []
    assert len(result.requests) == 1


@pytest.mark.parametrize("resumed", [False, True])
def test_repeated_cursor_fails(resumed: bool) -> None:
    result = make_driver().run(
        "projects",
        always(ScriptedResponse(json={"objects": [{"id": "same"}]})),
        resume_state=BraintrustResumeConfig(cursor="same") if resumed else None,
    )
    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert len(result.requests) == (1 if resumed else 2)


@pytest.mark.parametrize("body", [{}, {"objects": None}, {"error": "unexpected"}])
def test_malformed_page_does_not_succeed(body: dict[str, Any]) -> None:
    result = make_driver().run("projects", always(ScriptedResponse(json=body)))
    assert isinstance(result.raised, RESTClientRetryableError)


@pytest.mark.parametrize("status", [200, 404, 429, 500])
def test_credentials_and_error_classification(status: int) -> None:
    with scripted_network(always(ScriptedResponse(json={"objects": []}, status=status))) as network:
        if status in (429, 500):
            with pytest.raises(RESTClientRetryableError):
                validate_credentials(make_config(), 123)
        elif status == 404:
            with pytest.raises(HTTPError):
                validate_credentials(make_config(), 123)
        else:
            valid, message = validate_credentials(make_config(), 123)
            assert valid is (status == 200)
            if status == 401:
                assert message and "rejected the API key" in message
            elif status == 403:
                assert message and "permissions" in message
            else:
                assert message is None
    assert network.requests_log[0].param("limit") == "1"
    if status < 429:
        assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["authorization"] == "Bearer fake-braintrust-key"


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_non_retryable_messages(status: int) -> None:
    result = make_driver().run("projects", [ScriptedResponse(status=status)])
    assert isinstance(result.raised, HTTPError)
    messages = [
        message
        for pattern, message in BraintrustSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert len(messages) == 1
    assert messages[0] and "API key" in messages[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://",
        "https://example.com/v1",
        "https://user:pass@example.com",
        "https://example.com?q=1",
        "https://example.com#fragment",
        "https://example.com:80",
        "https://example.com:bad",
        "https://[",
    ],
)
def test_invalid_urls_fail_before_http(url: str) -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials(make_config(api_url=url), 123)
    assert not valid
    assert message and "HTTPS API URL" in message
    assert network.requests_log == []


def test_private_host_rejected_for_probe_and_sync() -> None:
    with scripted_network([]) as network, patch(HOST_CHECK, return_value=(False, "private host")):
        valid, message = validate_credentials(make_config(), 123)
        assert not valid
        assert message and "public IP address" in message
        result = make_driver().run("projects", [])
    assert isinstance(result.raised, ValueError)
    assert "public IP address" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


def test_redirect_does_not_forward_credentials() -> None:
    with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://other.example.com"})]) as network:
        with pytest.raises(ValueError, match="refusing to follow"):
            validate_credentials(make_config(), 123)
    assert len(network.requests_log) == 1


def test_blank_key_does_not_accept_anonymous_access() -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials(make_config(api_key=" "), 123)
    assert not valid
    assert message and "API key" in message
    assert network.requests_log == []
