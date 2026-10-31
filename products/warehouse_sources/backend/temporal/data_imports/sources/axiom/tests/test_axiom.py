from collections.abc import Iterable
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock

import structlog
from requests.exceptions import HTTPError
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.axiom import AxiomResumeConfig, axiom_source
from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.source import AxiomSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.axiom import AxiomSourceConfig


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def make_inputs(table: str) -> SourceInputs:
    return SourceInputs(
        schema_name=table,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.mark.parametrize(
    "table,path",
    [
        ("datasets", "datasets"),
        ("monitors", "monitors"),
        ("annotations", "annotations"),
        ("users", "users"),
        ("groups", "rbac/groups"),
    ],
)
@pytest.mark.parametrize("rows", [[], [{"id": "record-1"}, {"id": "record-2"}]])
@pytest.mark.parametrize("org_id", [None, "example-org"])
def test_single_page_full_refresh(table: str, path: str, rows: list[dict[str, str]], org_id: str | None) -> None:
    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token", org_id=org_id)).run(
        table, [ScriptedResponse(json=rows)]
    )

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/v2/{path}"]
    request = result.requests[0]
    assert request.headers["authorization"] == "Bearer test-token"
    assert request.headers.get("x-axiom-org-id") == org_id
    assert request.query == {}
    assert request.body is None
    assert result.saved_states == []


@pytest.mark.parametrize("table,path", [("dashboards", "dashboards"), ("saved_queries", "apl-starred-queries")])
@pytest.mark.parametrize("terminal_page", [[], [{"id": "last-record"}]])
def test_offset_pages_stop_and_save_next_offset(table: str, path: str, terminal_page: list[dict[str, str]]) -> None:
    first_page = [{"id": f"record-{index}"} for index in range(100)]
    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token")).run(
        table, [ScriptedResponse(json=first_page), ScriptedResponse(json=terminal_page)]
    )

    assert result.raised is None
    assert result.rows == first_page + terminal_page
    assert result.paths == [f"/v2/{path}", f"/v2/{path}"]
    extra_params = {"who": ("all",)} if table == "saved_queries" else {}
    assert result.queries == [
        {"offset": ("0",), "limit": ("100",), **extra_params},
        {"offset": ("100",), "limit": ("100",), **extra_params},
    ]
    assert all(request.headers["authorization"] == "Bearer test-token" for request in result.requests)
    assert result.saved_states == [AxiomResumeConfig(offset=100)]


@pytest.mark.parametrize("saved_offset", [None, 200])
def test_resume_uses_saved_offset(requests_mock: Mocker, manager: MagicMock, saved_offset: int | None) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = None if saved_offset is None else AxiomResumeConfig(offset=saved_offset)
    endpoint = requests_mock.get("https://api.axiom.co/v2/dashboards", json=[{"id": "last-record"}])
    response = axiom_source(AxiomSourceConfig(api_token="test-token"), make_inputs("dashboards"), manager)

    pages = cast(Iterable[list[dict[str, str]]], response.items())
    assert [row for page in pages for row in page] == [{"id": "last-record"}]
    assert endpoint.last_request is not None
    assert endpoint.last_request.qs["offset"] == [str(saved_offset or 0)]
    manager.save_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once_with()


@pytest.mark.parametrize("org_id", [None, "example-org"])
def test_credentials_use_one_request(org_id: str | None) -> None:
    with scripted_network([ScriptedResponse(json=[])]) as network:
        assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token", org_id=org_id), 1) == (
            True,
            None,
        )

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == "/v2/datasets"
    assert request.headers["authorization"] == "Bearer test-token"
    assert request.headers.get("x-axiom-org-id") == org_id


def test_credentials_fall_back_to_an_authorized_resource() -> None:
    with scripted_network(
        [ScriptedResponse(status=403), ScriptedResponse(status=403), ScriptedResponse(json=[])]
    ) as network:
        assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token"), 1) == (True, None)

    assert [request.path for request in network.requests_log] == [
        "/v2/datasets",
        "/v2/monitors",
        "/v2/annotations",
    ]


@pytest.mark.parametrize(
    "schema_name,path,query",
    [
        ("dashboards", "/v2/dashboards", {"limit": ("1",)}),
        ("monitor_history", "/v2/monitors", {}),
    ],
)
def test_credentials_use_selected_resource(schema_name: str, path: str, query: dict[str, tuple[str, ...]]) -> None:
    with scripted_network([ScriptedResponse(json=[])]) as network:
        assert AxiomSource().validate_credentials(AxiomSourceConfig(api_token="test-token"), 1, schema_name) == (
            True,
            None,
        )

    assert len(network.requests_log) == 1
    assert network.requests_log[0].path == path
    assert network.requests_log[0].query == query


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {"code": 401, "message": "auth token not provided"}, "Axiom rejected the token"),
    ],
)
def test_auth_errors_match_validation_and_pipeline(status: int, body: dict[str, Any], expected: str) -> None:
    source = AxiomSource()
    config = AxiomSourceConfig(api_token="test-token")

    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, message = source.validate_credentials(config, 1, "datasets")
    assert valid is False
    assert message is not None and message.startswith(expected)
    result = SourceDriver(source, config).run("datasets", [ScriptedResponse(status=status, json=body)])
    assert [request.path for request in network.requests_log] == ["/v2/datasets"]
    assert result.paths == ["/v2/datasets"]
    assert isinstance(result.raised, HTTPError)
    matching_messages = [
        mapped for pattern, mapped in source.get_non_retryable_errors().items() if pattern in str(result.raised)
    ]
    assert matching_messages == [message]
    assert "test-token" not in str(result.raised)


@pytest.mark.parametrize(
    "status,expected",
    [
        (404, HTTPError),
        (429, (False, "Couldn't reach Axiom to check your credentials. Try again in a few minutes.")),
        (503, (False, "Couldn't reach Axiom to check your credentials. Try again in a few minutes.")),
    ],
)
def test_probe_preserves_non_auth_failures(status: int, expected: type[Exception] | tuple[bool, str]) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"code": status}))) as network:
        source = AxiomSource()
        config = AxiomSourceConfig(api_token="test-token")
        if isinstance(expected, tuple):
            assert source.validate_credentials(config, 1) == expected
        else:
            with pytest.raises(expected):
                source.validate_credentials(config, 1)

    assert {request.path for request in network.requests_log} == {"/v2/datasets"}


@pytest.mark.parametrize("body", [{"message": "Unexpected response"}, None])
def test_unexpected_response_is_not_imported_as_a_record(body: dict[str, str] | None) -> None:
    config = AxiomSourceConfig(api_token="test-token")
    answer = ScriptedResponse(json=body, body=b"null" if body is None else None)

    result = SourceDriver(AxiomSource(), config).run("datasets", [answer])
    assert isinstance(result.raised, ValueError)
    assert "Required a list response body" in str(result.raised)
    assert result.rows == []

    with scripted_network([answer]) as network:
        with pytest.raises(ValueError, match="Required a list response body"):
            AxiomSource().validate_credentials(config, 1)
    assert [request.path for request in network.requests_log] == ["/v2/datasets"]


def history_query(start: str, end: str) -> dict[str, tuple[str, ...]]:
    return {"startTime": (start,), "endTime": (end,)}


@time_machine.travel("2025-03-01T00:00:00Z", tick=False)
@pytest.mark.parametrize(
    "created_at,incremental,last_value,expected_queries",
    [
        (
            "2025-02-17T00:00:00Z",
            False,
            None,
            [
                history_query("2025-02-17T00:00:00Z", "2025-02-24T00:00:00Z"),
                history_query("2025-02-24T00:00:00Z", "2025-03-01T00:00:00Z"),
            ],
        ),
        (
            "2025-02-17T00:00:00Z",
            False,
            "2025-02-26T12:00:00Z",
            [
                history_query("2025-02-17T00:00:00Z", "2025-02-24T00:00:00Z"),
                history_query("2025-02-24T00:00:00Z", "2025-03-01T00:00:00Z"),
            ],
        ),
        (
            "2025-02-17T00:00:00Z",
            True,
            "2025-02-26T12:00:00.500Z",
            [history_query("2025-02-26T12:00:00Z", "2025-03-01T00:00:00Z")],
        ),
        (
            "2025-02-27T00:00:00Z",
            True,
            "2025-02-20T00:00:00Z",
            [history_query("2025-02-27T00:00:00Z", "2025-03-01T00:00:00Z")],
        ),
        ("2025-02-17T00:00:00Z", True, "2025-03-02T00:00:00Z", []),
        (
            None,
            False,
            None,
            [
                history_query("2024-12-01T00:00:00Z", "2024-12-08T00:00:00Z"),
                *[{} for _ in range(11)],
                history_query("2025-02-23T00:00:00Z", "2025-03-01T00:00:00Z"),
            ],
        ),
    ],
)
def test_monitor_history_windows(
    created_at: str | None,
    incremental: bool,
    last_value: str | None,
    expected_queries: list[dict[str, tuple[str, ...]]],
) -> None:
    monitor: dict[str, str] = {"id": "monitor-1", "name": "Example monitor"}
    if created_at is not None:
        monitor["createdAt"] = created_at
    script = [ScriptedResponse(json=[monitor])] + [ScriptedResponse(json=[]) for _ in expected_queries]

    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token")).run(
        "monitor_history",
        script,
        should_use_incremental_field=incremental,
        incremental_field="timestamp" if incremental else None,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.rows == []
    assert result.paths == ["/v2/monitors"] + ["/v2/monitors/monitor-1/history"] * len(expected_queries)
    queries = result.queries[1:]
    assert len(queries) == len(expected_queries)
    for query, expected in zip(queries, expected_queries):
        if expected:
            assert query == expected


def history_row(timestamp: str, state: str = "open", name: str = "Triggered: Example monitor") -> dict[str, str]:
    return {"checkId": "monitor-1", "name": name, "state": state, "timestamp": timestamp}


@time_machine.travel("2025-03-01T00:00:00Z", tick=False)
def test_monitor_history_rows_keep_each_delivery_once() -> None:
    first_window = [
        history_row("2025-02-19T10:00:00Z"),
        history_row("2025-02-19T10:00:00Z"),
        history_row("2025-02-19T10:00:00Z", state="closed", name="Resolved: Example monitor"),
        history_row("2025-02-16T23:59:59Z"),
        history_row("2025-02-24T00:00:00Z"),
        history_row("not-a-timestamp"),
    ]
    second_window = [history_row("2025-02-24T00:00:00Z"), history_row("2025-02-24T00:00:00.250Z")]

    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token")).run(
        "monitor_history",
        [
            ScriptedResponse(json=[{"id": "monitor-1", "createdAt": "2025-02-17T00:00:00Z"}]),
            ScriptedResponse(json=first_window),
            ScriptedResponse(json=second_window),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {**history_row("2025-02-19T10:00:00Z"), "deliveryIndex": 0},
        {**history_row("2025-02-19T10:00:00Z"), "deliveryIndex": 1},
        {
            **history_row("2025-02-19T10:00:00Z", state="closed", name="Resolved: Example monitor"),
            "deliveryIndex": 0,
        },
        {**history_row("not-a-timestamp"), "deliveryIndex": 0},
        {**history_row("2025-02-24T00:00:00Z"), "deliveryIndex": 0},
        {**history_row("2025-02-24T00:00:00.250Z"), "deliveryIndex": 0},
    ]


@time_machine.travel("2025-03-01T00:00:00Z", tick=False)
def test_monitor_history_keeps_rows_near_fractional_window_bounds() -> None:
    row = history_row("2025-02-24T00:00:00.250Z")

    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token")).run(
        "monitor_history",
        [
            ScriptedResponse(json=[{"id": "monitor-1", "createdAt": "2025-02-17T00:00:00.500Z"}]),
            ScriptedResponse(json=[]),
            ScriptedResponse(json=[row]),
        ],
    )

    assert result.raised is None
    assert result.queries[1:] == [
        history_query("2025-02-17T00:00:00Z", "2025-02-24T00:00:00Z"),
        history_query("2025-02-24T00:00:00Z", "2025-03-01T00:00:00Z"),
    ]
    assert result.rows == [{**row, "deliveryIndex": 0}]


def test_monitor_history_does_not_claim_resumability() -> None:
    inputs = cast(SourceInputs, MagicMock(schema_name="monitor_history", should_use_incremental_field=False))
    response = axiom_source(AxiomSourceConfig(api_token="test-token"), inputs, MagicMock())
    assert response.supports_resume is False


@time_machine.travel("2025-03-01T00:00:00Z", tick=False)
@pytest.mark.parametrize("status,raises", [(404, False), (403, True)])
def test_monitor_history_skips_only_deleted_monitors(status: int, raises: bool) -> None:
    monitors = [
        {"id": "monitor-1", "createdAt": "2025-02-27T00:00:00Z"},
        {"id": "monitor-2", "createdAt": "2025-02-27T00:00:00Z"},
    ]
    row = {**history_row("2025-02-28T00:00:00Z"), "checkId": "monitor-2"}

    result = SourceDriver(AxiomSource(), AxiomSourceConfig(api_token="test-token")).run(
        "monitor_history",
        [
            ScriptedResponse(json=monitors),
            ScriptedResponse(status=status, json={"code": status}),
            ScriptedResponse(json=[row]),
        ],
    )

    if raises:
        assert isinstance(result.raised, HTTPError)
        assert result.rows == []
    else:
        assert result.raised is None
        assert result.paths == ["/v2/monitors", "/v2/monitors/monitor-1/history", "/v2/monitors/monitor-2/history"]
        assert result.rows == [{**row, "deliveryIndex": 0}]
