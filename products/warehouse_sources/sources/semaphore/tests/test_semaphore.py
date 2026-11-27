import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network
from products.warehouse_sources.sources.semaphore._config import SemaphoreSourceConfig
from products.warehouse_sources.sources.semaphore.semaphore import SemaphoreResumeConfig
from products.warehouse_sources.sources.semaphore.settings import NOT_FOUND_ERROR
from products.warehouse_sources.sources.semaphore.source import SemaphoreSource

BASE_URL = "https://example.semaphoreci.com/api/v1alpha/"
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "test-semaphore-token"


@pytest.fixture
def config() -> SemaphoreSourceConfig:
    return SemaphoreSourceConfig(api_token=TOKEN, organization="example", project_id=PROJECT_ID)


def response(body: object, status: int = 200, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Content-Type": "application/json"}
    if next_url:
        headers["Link"] = f'<{next_url}>; rel="next"'
    return ScriptedResponse(status=status, body=json.dumps(body).encode(), headers=headers)


@pytest.mark.parametrize(
    ("table", "path", "key", "params"),
    [
        ("workflows", "plumber-workflows", "wf_id", {"project_id": [PROJECT_ID]}),
        ("pipelines", "pipelines", "ppl_id", {"project_id": [PROJECT_ID]}),
        ("deployment_targets", "deployment_targets", "id", {"project_id": [PROJECT_ID]}),
        ("flaky_tests", f"projects/{PROJECT_ID}/test_results/flaky_tests", "id", {}),
    ],
)
@pytest.mark.parametrize("empty_terminal", [False, True])
def test_transport_and_terminal_page(
    config: SemaphoreSourceConfig,
    table: str,
    path: str,
    key: str,
    params: dict[str, list[str]],
    empty_terminal: bool,
) -> None:
    next_url = f"{BASE_URL}{path}?page=2"
    first = {key: "row-1", "created_at": {"seconds": 1704067200, "nanos": 123456000}}
    last = [] if empty_terminal else [{key: "row-2", "created_at": "2024-01-02T00:00:00Z"}]
    result = SourceDriver(SemaphoreSource(), config).run(table, [response([first], next_url=next_url), response(last)])
    rows = result.rows
    assert [row[key] for row in rows] == (["row-1"] if empty_terminal else ["row-1", "row-2"])
    assert rows[0]["created_at"] == datetime(2024, 1, 1, 0, 0, 0, 123456, UTC)
    assert result.response is not None
    assert result.response.primary_keys == [key]
    requests = result.requests
    assert urlsplit(requests[0].url).path == f"/api/v1alpha/{path}"
    assert parse_qs(urlsplit(requests[0].url).query) == params
    assert requests[1].url == next_url
    for request in requests:
        assert request.headers["authorization"] == f"Token {TOKEN}"
        assert request.headers["user-agent"] == "SemaphoreCI v2.0 Client"
    assert result.saved_states[0] == SemaphoreResumeConfig(next_url=next_url)
    assert result.saved_states[-1] == SemaphoreResumeConfig(completed=True)


@pytest.mark.parametrize("resumed", [False, True])
def test_members_walk_page_numbers_until_total_pages(config: SemaphoreSourceConfig, resumed: bool) -> None:
    pages = [
        response({"members": [{"id": "member-1", "roles": []}], "total_pages": 2}),
        response({"members": [{"id": "member-2", "roles": []}], "total_pages": 2}),
    ]
    result = SourceDriver(SemaphoreSource(), config).run(
        "members",
        pages[1:] if resumed else pages,
        resume_state=SemaphoreResumeConfig(paginator_state={"page": 1}) if resumed else None,
    )
    assert [row["id"] for row in result.rows] == (["member-2"] if resumed else ["member-1", "member-2"])
    assert [parse_qs(urlsplit(request.url).query) for request in result.requests] == (
        [{"page_no": ["1"]}] if resumed else [{"page_no": ["0"]}, {"page_no": ["1"]}]
    )
    assert urlsplit(result.requests[0].url).path == "/api/v1alpha/members"
    if not resumed:
        assert result.saved_states[0] == SemaphoreResumeConfig(paginator_state={"page": 1})
    assert result.saved_states[-1] == SemaphoreResumeConfig(completed=True)


@pytest.mark.parametrize(
    "last_page",
    [
        {"deployments": [{"id": "deploy-2", "target_id": "target-a"}], "cursor_before": 0, "cursor_after": 0},
        {"deployments": [], "cursor_before": 1685000000000000, "cursor_after": 0},
    ],
)
def test_deployment_history_walks_each_target_back_in_time(
    config: SemaphoreSourceConfig, last_page: dict[str, Any]
) -> None:
    cursor = 1685096881121173
    result = SourceDriver(SemaphoreSource(), config).run(
        "deployment_history",
        [
            response([{"id": "target-a"}, {"id": "target-b"}]),
            response(
                {
                    "deployments": [{"id": "deploy-1", "target_id": "target-a"}],
                    "cursor_before": cursor,
                    "cursor_after": 0,
                }
            ),
            response(last_page),
            response({"deployments": [{"id": "deploy-3", "target_id": "target-b"}], "cursor_before": 0}),
        ],
    )
    assert result.raised is None
    expected = ["deploy-1", *[row["id"] for row in last_page["deployments"]], "deploy-3"]
    assert [row["id"] for row in result.rows] == expected
    assert [(urlsplit(r.url).path, parse_qs(urlsplit(r.url).query)) for r in result.requests] == [
        ("/api/v1alpha/deployment_targets", {"project_id": [PROJECT_ID]}),
        ("/api/v1alpha/deployment_targets/target-a/history", {}),
        (
            "/api/v1alpha/deployment_targets/target-a/history",
            {"cursor_type": ["BEFORE"], "cursor_value": [str(cursor)]},
        ),
        ("/api/v1alpha/deployment_targets/target-b/history", {}),
    ]


def test_deployment_history_fails_on_a_repeated_cursor(config: SemaphoreSourceConfig) -> None:
    page = {"deployments": [{"id": "deploy-1", "target_id": "target-a"}], "cursor_before": 1685096881121173}
    result = SourceDriver(SemaphoreSource(), config).run(
        "deployment_history", [response([{"id": "target-a"}]), response(page), response(page)]
    )
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 3


@pytest.mark.parametrize("resumed", [False, True])
def test_flaky_test_disruptions_fan_out_over_flaky_tests(config: SemaphoreSourceConfig, resumed: bool) -> None:
    base = f"projects/{PROJECT_ID}/test_results/flaky_tests"
    first_path = f"{base}/flaky-1/disruptions"
    first_child = [
        response(
            [{"pipeline_id": "pipeline-1", "created_at": "2025-05-30T14:22:01Z"}],
            next_url=f"{BASE_URL}{first_path}?page=2",
        ),
        response([{"pipeline_id": "pipeline-2", "created_at": "2025-05-31T09:00:00Z"}]),
    ]
    result = SourceDriver(SemaphoreSource(), config).run(
        "flaky_test_disruptions",
        [
            response([{"id": "flaky-1"}, {"id": "flaky-2"}]),
            *([] if resumed else first_child),
            response([{"pipeline_id": "pipeline-3", "created_at": "2025-06-01T00:00:00Z"}]),
        ],
        resume_state=(
            SemaphoreResumeConfig(paginator_state={"completed": [first_path], "current": None, "child_state": None})
            if resumed
            else None
        ),
    )
    assert result.raised is None
    expected = (
        [("flaky-2", "pipeline-3")]
        if resumed
        else [
            ("flaky-1", "pipeline-1"),
            ("flaky-1", "pipeline-2"),
            ("flaky-2", "pipeline-3"),
        ]
    )
    assert [(row["flaky_test_id"], row["pipeline_id"]) for row in result.rows] == expected
    assert result.rows[-1]["created_at"] == datetime(2025, 6, 1, tzinfo=UTC)
    paths = [urlsplit(request.url).path for request in result.requests]
    assert paths[0] == f"/api/v1alpha/{base}"
    assert paths[-1] == f"/api/v1alpha/{base}/flaky-2/disruptions"
    assert len(paths) == (2 if resumed else 4)
    assert all(state.paginator_state is not None for state in result.saved_states)


@pytest.mark.parametrize(
    ("table", "incremental", "watermark", "expected"),
    [
        ("workflows", True, datetime(2024, 1, 1, tzinfo=UTC), "1704067199"),
        ("workflows", True, "2024-01-01T00:00:00.999999Z", "1704067199"),
        ("workflows", True, None, None),
        ("workflows", False, "2024-01-01T00:00:00Z", None),
        ("pipelines", True, "2024-01-01T00:00:00Z", None),
        ("deployment_targets", True, "2024-01-01T00:00:00Z", None),
    ],
)
def test_incremental_filter(
    config: SemaphoreSourceConfig,
    table: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        table,
        [response([])],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    params = parse_qs(urlsplit(result.requests[-1].url).query)
    assert params == {"project_id": [PROJECT_ID], **({"created_after": [expected]} if expected else {})}
    if table == "workflows" and incremental:
        assert result.response is not None
        assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("completed", [False, True])
def test_resume_skips_saved_pages(config: SemaphoreSourceConfig, completed: bool) -> None:
    next_url = f"{BASE_URL}plumber-workflows?project_id={PROJECT_ID}&page=3"
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [response([{"wf_id": "last"}])],
        resume_state=SemaphoreResumeConfig(next_url=next_url, completed=completed),
    )
    if completed:
        assert result.rows == []
        assert result.requests == []
    else:
        assert result.rows == [{"wf_id": "last"}]
        assert result.requests[-1].url == next_url
        assert result.saved_states == [SemaphoreResumeConfig(completed=True)]


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [(404, NOT_FOUND_ERROR)],
)
def test_auth_errors_are_actionable_and_non_retryable(
    config: SemaphoreSourceConfig,
    status: int,
    expected_message: str,
) -> None:
    source = SemaphoreSource()
    with scripted_network([response({}, status)]) as network:
        valid, message = source.validate_credentials(config, 1)
    assert valid is False
    assert message == expected_message
    assert len(network.requests_log) == 1
    result = SourceDriver(source, config).run("workflows", [response({}, status)])
    assert isinstance(result.raised, HTTPError)
    assert f"{status} Client Error" in str(result.raised)
    assert TOKEN not in str(result.raised)
    assert len(result.requests) == 1


def test_validation_reads_only_one_page(config: SemaphoreSourceConfig) -> None:
    with scripted_network([response([], next_url=BASE_URL + "plumber-workflows?page=2")]) as network:
        assert SemaphoreSource().validate_credentials(config, 1) == (True, None)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["authorization"] == f"Token {TOKEN}"
    assert parse_qs(urlsplit(request.url).query) == {"project_id": [PROJECT_ID]}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization", "https://example.com"),
        ("organization", "example.com"),
        ("organization", "example@evil.com"),
        ("organization", "bad\n"),
        ("organization", "-bad"),
        ("organization", "a" * 64),
        ("project_id", "not-a-uuid"),
    ],
)
def test_invalid_configuration_never_sends_credentials(
    config: SemaphoreSourceConfig,
    field: str,
    value: str,
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        assert SemaphoreSource().validate_credentials(config, 1)[0] is False
    result = SourceDriver(SemaphoreSource(), config).run("workflows", [])
    assert isinstance(result.raised, ValueError)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize(
    "next_url", ["https://example.com/steal", "http://example.semaphoreci.com/api/v1alpha/pipelines"]
)
@pytest.mark.parametrize("resumed", [False, True])
def test_pagination_cannot_send_token_to_another_origin(
    config: SemaphoreSourceConfig,
    next_url: str,
    resumed: bool,
) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [response([{"wf_id": "first"}], next_url=next_url)],
        resume_state=SemaphoreResumeConfig(next_url=next_url) if resumed else None,
    )
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == (0 if resumed else 1)


@pytest.mark.parametrize("body", [{"error": "unexpected"}, None])
def test_malformed_success_does_not_silently_complete(config: SemaphoreSourceConfig, body: Any) -> None:
    result = SourceDriver(SemaphoreSource(), config).run("workflows", [response(body)])
    assert isinstance(result.raised, ValueError)
    assert result.saved_states == []


def test_invalid_watermark_does_not_run_a_full_refresh(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows", [], should_use_incremental_field=True, db_incremental_field_last_value="invalid"
    )
    assert isinstance(result.raised, ValueError)
    assert "sync position" in str(result.raised)
    assert result.requests == []


def test_invalid_created_at_does_not_save_a_checkpoint(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows", [response([{"wf_id": "invalid", "created_at": "invalid"}])]
    )
    assert isinstance(result.raised, ValueError)
    assert "invalid creation time" in str(result.raised)
    assert result.saved_states == []


def test_redirects_are_not_followed(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [ScriptedResponse(status=302, headers={"Location": "https://example.com/steal"}, json={})],
    )
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 1
