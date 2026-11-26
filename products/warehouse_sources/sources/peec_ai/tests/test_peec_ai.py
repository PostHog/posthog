from datetime import UTC, date, datetime, timedelta

import pytest

import requests

from products.warehouse_sources.sources.peec_ai._config import PeecAISourceConfig
from products.warehouse_sources.sources.peec_ai.peec_ai import PeecAIResumeConfig, validate_credentials
from products.warehouse_sources.sources.peec_ai.source import PeecAISource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


@pytest.fixture
def config() -> PeecAISourceConfig:
    return PeecAISourceConfig(api_key="example-secret", project_id="or_example", start_date="2025-01-01")


@pytest.fixture
def driver(config: PeecAISourceConfig) -> SourceDriver:
    return SourceDriver(PeecAISource(), config)


@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2025-06-10", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-06-10", "2025-06-10"),
        (True, date(2025, 6, 10), "2025-06-10"),
        (True, datetime(2025, 6, 10, 12, tzinfo=UTC), "2025-06-10"),
        (True, "2024-06-10", "2025-01-01"),
    ],
)
def test_chat_date_filter(
    driver: SourceDriver,
    incremental: bool,
    watermark: str | date | datetime | None,
    expected: str,
) -> None:
    result = driver.run(
        "chats",
        [ScriptedResponse(json={"data": [], "total_count": 0})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.requests[0].param("start_date") == expected
    assert result.requests[0].param("end_date") == datetime.now(UTC).date().isoformat()
    assert result.requests[0].param("sort") == "asc"
    assert result.response is not None
    assert result.response.sort_mode == "asc"


def test_resume_preserves_date_range_after_watermark_advances(driver: SourceDriver) -> None:
    result = driver.run(
        "chats",
        [ScriptedResponse(json={"data": [{"id": "last"}], "total_count": 5})],
        resume_state=PeecAIResumeConfig(offset=4, start_date="2025-06-01", end_date="2025-06-30"),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-06-15",
    )

    assert result.raised is None
    assert result.rows == [{"id": "last"}]
    assert result.requests[0].param("offset") == "4"
    assert result.requests[0].param("start_date") == "2025-06-01"
    assert result.requests[0].param("end_date") == "2025-06-30"


def test_actions_paginate_through_post_body(driver: SourceDriver) -> None:
    first_page = [{"id": f"action_{index}"} for index in range(1000)]
    last_row = {"id": "last"}
    result = driver.run(
        "actions",
        [
            ScriptedResponse(json={"data": first_page, "total_count": 1001}),
            ScriptedResponse(json={"data": [last_row], "total_count": 1001}),
        ],
    )

    assert result.raised is None
    assert result.rows == [*first_page, last_row]
    assert len(result.requests) == 2
    for offset, request in zip([0, 1000], result.requests, strict=True):
        assert request.method == "POST"
        assert request.url == "https://api.peec.ai/customer/v1/actions/list"
        assert request.json() == {
            "project_id": "or_example",
            "order_by": "created_at",
            "direction": "asc",
            "limit": 1000,
            "offset": offset,
        }


REPORT_BODY = {"dimensions": ["date", "model_channel_id"], "order_by": [{"field": "date", "direction": "asc"}]}


@pytest.mark.parametrize(
    "endpoint,path,body,incremental,watermark,expected_start,sort_mode",
    [
        ("brand_report", "reports/brands", REPORT_BODY, False, "2025-06-10", "2025-01-01", "asc"),
        ("brand_report", "reports/brands", REPORT_BODY, True, "2025-06-10", "2025-06-10", "asc"),
        ("domain_report", "reports/domains", REPORT_BODY, True, None, "2025-01-01", "asc"),
        ("url_report", "reports/urls", REPORT_BODY, True, date(2025, 6, 10), "2025-06-10", "asc"),
        ("search_fanout_queries", "queries/search", {"view": "rows"}, True, "2025-06-10", "2025-06-10", None),
        ("search_fanout_queries", "queries/search", {"view": "rows"}, True, "2024-06-10", "2025-01-01", None),
        ("products", "products/list", {"order_by": "name", "direction": "asc"}, True, "2025-06-10", "2025-01-01", None),
    ],
)
def test_date_ranged_post_endpoints_send_window_in_body(
    driver: SourceDriver,
    endpoint: str,
    path: str,
    body: dict,
    incremental: bool,
    watermark: str | date | None,
    expected_start: str,
    sort_mode: str | None,
) -> None:
    result = driver.run(
        endpoint,
        [ScriptedResponse(json={"data": [], "total_count": 0})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.method == "POST"
    assert request.url == f"https://api.peec.ai/customer/v1/{path}"
    assert request.json() == {
        **body,
        "project_id": "or_example",
        "start_date": expected_start,
        "end_date": datetime.now(UTC).date().isoformat(),
        "limit": 1000,
        "offset": 0,
    }
    assert result.response is not None
    assert result.response.sort_mode == sort_mode


def test_report_without_total_count_stops_on_short_page_and_lifts_keys(driver: SourceDriver) -> None:
    first_page = [
        {"brand": {"id": f"kw_{index}", "name": "Example"}, "model_channel": {"id": "openai-0"}, "date": "2025-01-01"}
        for index in range(1000)
    ]
    last_row = {"brand": {"id": "kw_last", "name": "Example"}, "model_channel": None, "date": "2025-01-02"}
    result = driver.run(
        "brand_report",
        [
            ScriptedResponse(json={"data": first_page}),
            ScriptedResponse(json={"data": [last_row]}),
        ],
    )

    assert result.raised is None
    assert [request.json()["offset"] for request in result.requests] == [0, 1000]
    assert len(result.rows) == 1001
    assert result.rows[0] == {**first_page[0], "brand_id": "kw_0", "model_channel_id": "openai-0"}
    assert result.rows[-1] == {**last_row, "brand_id": "kw_last", "model_channel_id": None}
    assert result.response is not None
    assert result.response.primary_keys == ["brand_id", "date", "model_channel_id"]


def test_search_fanout_rows_get_chat_and_query_keys(driver: SourceDriver) -> None:
    row = {
        "prompt": {"id": "pr_example"},
        "chat": {"id": "ch_example"},
        "model_channel": {"id": "openai-0"},
        "date": "2025-01-01",
        "query": {"index": 0, "text": "example query"},
    }
    result = driver.run("search_fanout_queries", [ScriptedResponse(json={"data": [row], "total_count": 1})])

    assert result.raised is None
    assert result.rows == [{**row, "chat_id": "ch_example", "query_index": 0}]
    assert result.response is not None
    assert result.response.primary_keys == ["chat_id", "query_index"]


def test_tag_groups_fetch_one_unpaginated_page(driver: SourceDriver) -> None:
    rows = [{"group": "persona", "color": "blue", "tag_count": 3}, {"group": "region", "color": None, "tag_count": 1}]
    result = driver.run("tag_groups", [ScriptedResponse(json={"data": rows})])

    assert result.raised is None
    assert result.items == [rows]
    assert result.response is not None
    assert result.response.primary_keys == ["group"]
    assert len(result.requests) == 1
    assert result.requests[0].query == {"project_id": ("or_example",)}
    assert result.saved_states == []


@pytest.mark.parametrize("project_id", [None, "or_example"])
def test_credential_probe_uses_one_small_request(config: PeecAISourceConfig, project_id: str | None) -> None:
    config.project_id = project_id
    with scripted_network([ScriptedResponse(json={"data": [], "total_count": 0})]) as network:
        assert validate_credentials(config, "v1") == (True, None)

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.query == {"limit": ("1",), **({"project_id": (project_id,)} if project_id else {})}
    assert request.headers["x-api-key"] == "example-secret"


@pytest.mark.parametrize(
    "status,body,message",
    [
        (400, "Missing API Key", "Check your API key"),
    ],
)
def test_credential_and_sync_errors(
    config: PeecAISourceConfig, driver: SourceDriver, status: int, body: str, message: str
) -> None:
    response = ScriptedResponse(status=status, json={"message": body})
    with scripted_network([response]) as network:
        valid, reason = validate_credentials(config, "v1")
    assert not valid
    assert reason is not None and message in reason

    result = driver.run("brands", [response])
    assert isinstance(result.raised, requests.HTTPError)
    errors = PeecAISource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) and mapped == reason for pattern, mapped in errors.items())
    assert len(network.requests_log) == 1
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [429, 500])
def test_transient_probe_errors_are_not_invalid_credentials(config: PeecAISourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"message": "Try later"}))):
        with pytest.raises(requests.HTTPError):
            validate_credentials(config, "v1")


@pytest.mark.parametrize("start_date", ["", "not-a-date", "2025-02-30", "20250610"])
def test_invalid_start_date_does_not_call_api(config: PeecAISourceConfig, start_date: str) -> None:
    config.start_date = start_date
    with scripted_network([]) as network:
        assert validate_credentials(config, "v1") == (False, "Enter a valid start date in YYYY-MM-DD format.")
    assert network.requests_log == []


def test_future_start_date_does_not_call_api(config: PeecAISourceConfig) -> None:
    config.start_date = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    with scripted_network([]) as network:
        assert validate_credentials(config, "v1") == (False, "The start date must be today or earlier.")
    assert network.requests_log == []
