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


TODAY = datetime.now(UTC).date()
REPORT_BODY = {"dimensions": ["date", "model_channel_id"]}


def _day(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


@pytest.mark.parametrize(
    "endpoint,path,body",
    [
        ("brand_report", "reports/brands", REPORT_BODY),
        ("domain_report", "reports/domains", REPORT_BODY),
        ("url_report", "reports/urls", REPORT_BODY),
        ("search_fanout_queries", "queries/search", {"view": "rows"}),
    ],
)
@pytest.mark.parametrize(
    "incremental,watermark,expected_days",
    [
        (False, _day(1), [_day(2), _day(1), _day(0)]),
        (True, None, [_day(2), _day(1), _day(0)]),
        (True, _day(1), [_day(1), _day(0)]),
        (True, TODAY - timedelta(days=1), [_day(1), _day(0)]),
        (True, _day(5), [_day(2), _day(1), _day(0)]),
    ],
)
def test_daily_endpoints_request_one_day_per_window(
    config: PeecAISourceConfig,
    endpoint: str,
    path: str,
    body: dict,
    incremental: bool,
    watermark: str | date | None,
    expected_days: list[str],
) -> None:
    config.start_date = _day(2)
    result = SourceDriver(PeecAISource(), config).run(
        endpoint,
        always(ScriptedResponse(json={"data": [], "total_count": 0})),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert [request.url for request in result.requests] == [
        f"https://api.peec.ai/customer/v1/{path}" for _ in expected_days
    ]
    assert [request.json() for request in result.requests] == [
        {**body, "project_id": "or_example", "start_date": day, "end_date": day, "limit": 10000, "offset": 0}
        for day in expected_days
    ]
    assert result.response is not None
    assert result.response.sort_mode == "asc"


def test_products_send_the_whole_range_in_one_window(driver: SourceDriver) -> None:
    result = driver.run(
        "products",
        [ScriptedResponse(json={"data": [], "total_count": 0})],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-06-10",
    )

    assert result.raised is None
    assert [request.json() for request in result.requests] == [
        {
            "order_by": "name",
            "direction": "asc",
            "project_id": "or_example",
            "start_date": "2025-01-01",
            "end_date": TODAY.isoformat(),
            "limit": 1000,
            "offset": 0,
        }
    ]
    assert result.response is not None
    assert result.response.sort_mode is None


def _brand_row(brand_id: str, day: str, channel: dict | None = None) -> dict:
    return {"brand": {"id": brand_id, "name": "Example"}, "model_channel": channel, "date": day}


def test_daily_window_pages_until_short_page_then_moves_to_next_day(config: PeecAISourceConfig) -> None:
    config.start_date = _day(1)
    first_page = [_brand_row(f"kw_{index}", _day(1), {"id": "openai-0"}) for index in range(10000)]
    last_row = _brand_row("kw_last", _day(1))
    result = SourceDriver(PeecAISource(), config).run(
        "brand_report",
        [
            ScriptedResponse(json={"data": first_page}),
            ScriptedResponse(json={"data": [last_row]}),
            ScriptedResponse(json={"data": []}),
        ],
    )

    assert result.raised is None
    assert [(request.json()["start_date"], request.json()["offset"]) for request in result.requests] == [
        (_day(1), 0),
        (_day(1), 10000),
        (_day(0), 0),
    ]
    assert len(result.rows) == 10001
    assert result.rows[0] == {**first_page[0], "brand_id": "kw_0", "model_channel_id": "openai-0"}
    assert result.rows[-1] == {**last_row, "brand_id": "kw_last", "model_channel_id": None}
    assert result.saved_states[0] == PeecAIResumeConfig(
        offset=10000, start_date=_day(1), end_date=_day(0), window_date=_day(1)
    )
    assert result.response is not None
    assert result.response.primary_keys == ["brand_id", "date", "model_channel_id"]


def test_daily_resume_continues_inside_the_saved_window(driver: SourceDriver) -> None:
    result = driver.run(
        "domain_report",
        [
            ScriptedResponse(json={"data": [{"domain": "example.com"}], "total_count": 10001}),
            ScriptedResponse(json={"data": [], "total_count": 0}),
        ],
        resume_state=PeecAIResumeConfig(
            offset=10000, start_date="2025-06-01", end_date="2025-06-03", window_date="2025-06-02"
        ),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-06-15",
    )

    assert result.raised is None
    assert [(request.json()["start_date"], request.json()["offset"]) for request in result.requests] == [
        ("2025-06-02", 10000),
        ("2025-06-03", 0),
    ]


def test_search_fanout_rows_get_chat_and_query_keys(config: PeecAISourceConfig) -> None:
    config.start_date = _day(0)
    row = {
        "prompt": {"id": "pr_example"},
        "chat": {"id": "ch_example"},
        "model_channel": {"id": "openai-0"},
        "date": _day(0),
        "query": {"index": 0, "text": "example query"},
    }
    result = SourceDriver(PeecAISource(), config).run(
        "search_fanout_queries", [ScriptedResponse(json={"data": [row], "total_count": 1})]
    )

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
