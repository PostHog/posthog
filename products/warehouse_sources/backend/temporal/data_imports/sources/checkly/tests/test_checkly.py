from datetime import UTC, datetime, timedelta

import pytest
import time_machine

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.checkly import (
    ChecklyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.source import ChecklySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkly import (
    ChecklySourceConfig,
)

CONFIG = ChecklySourceConfig(api_key="fake-checkly-key", account_id="00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 6, 1, tzinfo=UTC)
DRIVER = SourceDriver(ChecklySource(), CONFIG)


@pytest.mark.parametrize(
    "name,api_version,path",
    [
        ("checks", "v2", "/v2/checks"),
        ("checks", "v3", "/v3/checks"),
        ("check_groups", "v2", "/v1/check-groups"),
        ("check_groups", "v3", "/v1/check-groups"),
        ("alert_channels", "v2", "/v1/alert-channels"),
        ("alert_channels", "v3", "/v1/alert-channels"),
    ],
)
def test_list_pagination_auth_and_terminal_page(name: str, api_version: str, path: str) -> None:
    result = DRIVER.run(
        name,
        [ScriptedResponse(json=[{"id": "a"}]), ScriptedResponse(json=[{"id": "b"}]), ScriptedResponse(json=[])],
        api_version=api_version,
    )
    assert result.raised is None
    assert result.items == [[{"id": "a"}], [{"id": "b"}]]
    assert result.paths == [path] * 3
    assert result.params("limit") == ["100"] * 3
    assert result.params("page") == ["1", "2", "3"]
    for request in result.requests:
        assert request.headers["authorization"] == "Bearer fake-checkly-key"
        assert request.headers["x-checkly-account"] == CONFIG.account_id
    assert [state.paginator_state for state in result.saved_states] == [{"page": 2}, {"page": 3}]
    assert result.response is not None
    on_complete = result.response.on_complete
    assert on_complete is not None
    with scripted_network([]):
        manager = on_complete.__self__
        manager.save_state(result.saved_states[-1])
        manager.confirm()
        manager.commit()
        assert manager.load_state() == result.saved_states[-1]
        on_complete()
        assert manager.load_state() is None


@pytest.mark.parametrize(
    "name,api_version",
    [
        ("checks", "v2"),
        ("checks", "v3"),
        ("check_groups", "v2"),
        ("alert_channels", "v2"),
    ],
)
def test_definitions_project_only_safe_metadata(name: str, api_version: str) -> None:
    result = DRIVER.run(
        name,
        [
            ScriptedResponse(
                json=[
                    {
                        "id": "check-a",
                        "request": {
                            "url": "https://hooks.slack.com/services/T000/B000/SECRET",
                            "basicAuth": {"username": "user", "password": "secret"},
                            "body": "password=secret",
                            "headers": [{"key": "Authorization", "value": "Bearer secret"}],
                            "queryParameters": [{"key": "token", "value": "secret"}],
                            "grpcConfig": {"metadata": [{"key": "authorization", "value": "Bearer secret"}]},
                        },
                        "heartbeat": {"pingToken": "secret", "pingUrl": "https://checklyhq.com/ping/secret"},
                        "script": "login('secret')",
                        "localSetupScript": "setup('secret')",
                        "localTearDownScript": "teardown('secret')",
                        "apiCheckDefaults": {
                            "basicAuth": {"username": "user", "password": "group-secret"},
                            "environmentVariables": [{"key": "TOKEN", "value": "group-secret"}],
                            "headers": [{"key": "X-Api-Key", "value": "group-secret"}],
                            "browserCheckDefaults": {"script": "login('group-secret')"},
                        },
                        "config": {"webhookUrl": "https://example.com/secret"},
                        "newProviderField": "future-secret",
                        "requiredOutcomes": ["login succeeds"],
                        "constraints": [{"type": "REQUIRED_OUTCOME", "value": "login succeeds"}],
                    }
                ]
            ),
            ScriptedResponse(json=[]),
        ],
        api_version=api_version,
    )
    assert result.raised is None
    assert result.items == [[{"id": "check-a"}]]


def test_statuses_are_unpaginated_and_exclude_null_statuses() -> None:
    result = DRIVER.run(
        "check_statuses",
        [ScriptedResponse(json=[None, {"checkId": "check-a", "hasFailures": False}])],
        api_version="v2",
    )
    assert result.raised is None
    assert result.items == [[{"checkId": "check-a", "hasFailures": False}]]
    assert result.paths == ["/v1/check-statuses"]
    assert result.queries == [{}]
    assert result.response is not None
    assert result.response.primary_keys == ["checkId"]


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected_from",
    [
        (False, NOW - timedelta(hours=2), NOW - timedelta(days=30)),
        (True, None, NOW - timedelta(days=30)),
        (True, NOW - timedelta(hours=2), NOW - timedelta(hours=2)),
        (True, "2026-05-31T22:00:00Z", NOW - timedelta(hours=2)),
        (True, NOW - timedelta(days=90), NOW - timedelta(days=30)),
    ],
)
def test_result_fanout_cursor_and_time_filters(incremental: bool, watermark: object, expected_from: datetime) -> None:
    result = DRIVER.run(
        "check_results",
        [
            ScriptedResponse(json=[{"id": "check-a"}, {"id": "check-b"}]),
            ScriptedResponse(
                json={"entries": [{"id": "result-a", "created_at": "2026-05-31T23:00:00Z"}], "nextId": "cursor-a"}
            ),
            ScriptedResponse(json={"entries": [], "nextId": None}),
            ScriptedResponse(
                json={"entries": [{"id": "result-a", "created_at": "2026-05-31T22:00:00Z"}], "nextId": None}
            ),
            ScriptedResponse(json=[]),
        ],
        api_version="v2",
        incremental_field="created_at" if incremental else None,
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    assert [row["checkId"] for row in result.rows] == ["check-a", "check-b"]
    assert result.items[0][0]["created_at"] == NOW - timedelta(hours=1)
    assert result.response is not None
    assert result.response.primary_keys == ["checkId", "id"]
    assert result.response.sort_mode == "desc"
    assert result.paths == [
        "/v2/checks",
        "/v2/check-results/check-a",
        "/v2/check-results/check-a",
        "/v2/check-results/check-b",
        "/v2/checks",
    ]
    for request in result.requests[1:4]:
        assert request.param("from") == str(int(expected_from.timestamp()))
        assert request.param("to") == str(int(NOW.timestamp()))
        assert request.param("resultType") == "ALL"
        fields = (request.param("fields") or "").split(",")
        assert {"id", "checkId", "created_at", "responseTime", "hasFailures"} <= set(fields)
        assert "apiCheckResult" not in fields
        assert "browserCheckResult" not in fields
        assert request.param("checkId") is None
        assert request.param("page") is None
    assert result.params("nextId")[1:4] == [None, "cursor-a", None]
    states = result.saved_states
    assert states[0].paginator_state["child_state"] == {"cursor": "cursor-a"}
    assert states[-1].paginator_state["completed"] == ["/v2/check-results/check-a", "/v2/check-results/check-b"]
    assert all(state.to_timestamp == int(NOW.timestamp()) for state in states)


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize("api_version", ["v2", "v3"])
def test_result_resume_preserves_window_and_skips_completed_checks(api_version: str) -> None:
    resume_state = ChecklyResumeConfig(
        paginator_state={
            "completed": ["/v2/check-results/check-a"],
            "current": "/v2/check-results/check-b",
            "child_state": {"cursor": "saved-cursor"},
        },
        from_timestamp=1700000000,
        to_timestamp=1700010000,
    )
    result = DRIVER.run(
        "check_results",
        [
            ScriptedResponse(json=[{"id": "check-a"}, {"id": "check-b"}]),
            ScriptedResponse(json={"entries": [{"id": "last"}], "nextId": None}),
            ScriptedResponse(json=[]),
        ],
        api_version=api_version,
        resume_state=resume_state,
    )
    assert result.raised is None
    assert result.items == [[{"id": "last", "checkId": "check-b"}]]
    assert result.paths == [f"/{api_version}/checks", "/v2/check-results/check-b", f"/{api_version}/checks"]
    assert result.requests[1].param("from") == "1700000000"
    assert result.requests[1].param("to") == "1700010000"
    assert result.requests[1].param("nextId") == "saved-cursor"


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize("watermark", [NOW, NOW + timedelta(hours=1)])
def test_no_requests_for_future_or_empty_window(watermark: datetime) -> None:
    result = DRIVER.run(
        "check_results",
        [],
        incremental_field="created_at",
        db_incremental_field_last_value=watermark,
    )
    assert result.items == []
    assert result.requests == []
    assert result.raised is None


@pytest.mark.parametrize(
    "name,watermark,error",
    [("unknown", None, "Unknown Checkly table"), ("check_results", "bad", "timestamp is invalid")],
)
def test_rejects_invalid_pipeline_inputs(name: str, watermark: object, error: str) -> None:
    result = DRIVER.run(
        name,
        [],
        incremental_field="created_at",
        db_incremental_field_last_value=watermark,
    )
    assert isinstance(result.raised, ValueError)
    assert error in str(result.raised)
    assert result.requests == []


@pytest.mark.parametrize(
    "status,schema,valid,message,path",
    [
        (200, None, True, None, "/v2/checks"),
        (401, None, False, "rejected your API key", "/v2/checks"),
        (403, None, True, None, "/v2/checks"),
        (403, "checks", False, "key permissions", "/v2/checks"),
        (401, "check_results", False, "rejected your API key", "/v2/checks"),
        (200, "alert_channels", True, None, "/v1/alert-channels"),
        (200, "check_groups", True, None, "/v1/check-groups"),
        (200, "check_statuses", True, None, "/v1/check-statuses"),
    ],
)
def test_credential_probe_and_auth_errors(
    status: int, schema: str | None, valid: bool, message: str | None, path: str
) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json=[] if status == 200 else {"statusCode": status, "error": "Unauthorized"})]
    ) as network:
        result, reason = validate_credentials(CONFIG, schema, "v2")
    assert result is valid
    assert reason is None if message is None else message in (reason or "")
    assert [request.path for request in network.requests_log] == [path]
    assert network.requests_log[0].query == ({} if schema == "check_statuses" else {"limit": ("1",)})
    assert network.requests_log[0].headers["authorization"] == "Bearer fake-checkly-key"
    if not valid:
        assert reason in ChecklySource().get_non_retryable_errors().values()


@pytest.mark.parametrize("status", [401, 403, 404])
def test_sync_http_errors_are_terminal(status: int) -> None:
    result = DRIVER.run(
        "checks", [ScriptedResponse(status=status, json={"statusCode": status, "error": "Unauthorized"})]
    )
    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    matches = [value for key, value in ChecklySource().get_non_retryable_errors().items() if key in str(result.raised)]
    assert len(matches) == (0 if status == 404 else 1)


@pytest.mark.parametrize("status", [429, 500])
def test_transient_errors_use_framework_retries(status: int) -> None:
    result = DRIVER.run("checks", [ScriptedResponse(status=status, json={"statusCode": status})] * 5)
    assert isinstance(result.raised, RESTClientRetryableError)
    assert len(result.requests) == 5


@pytest.mark.parametrize("api_version,path", [(None, "/v3/checks"), ("v2", "/v2/checks"), ("v3", "/v3/checks")])
def test_source_probe_uses_pinned_or_default_version(api_version: str | None, path: str) -> None:
    with scripted_network([ScriptedResponse(json=[])]) as network:
        assert ChecklySource().validate_credentials(CONFIG, team_id=1, api_version=api_version) == (True, None)
    assert [request.path for request in network.requests_log] == [path]


def test_unknown_schema_probe_makes_no_request() -> None:
    with scripted_network([]) as network:
        assert validate_credentials(CONFIG, "unknown", "v2") == (False, "Unknown Checkly table: unknown")
    assert network.requests_log == []


def test_credential_probe_preserves_unexpected_errors() -> None:
    with scripted_network([ScriptedResponse(status=404, json={"statusCode": 404})]):
        with pytest.raises(HTTPError):
            validate_credentials(CONFIG, None, "v2")


def test_unsupported_version_makes_no_request() -> None:
    result = DRIVER.run("checks", [], api_version="v1")
    assert isinstance(result.raised, ValueError)
    assert "API version is not supported" in str(result.raised)
    assert result.requests == []
