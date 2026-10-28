from urllib.parse import urlsplit

import pytest
import time_machine

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thousandeyes import (
    ThousandeyesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.source import ThousandeyesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.thousandeyes import (
    ThousandeyesResumeConfig,
)

BASE = "https://api.thousandeyes.com/v7/"


def read(
    name: str,
    script: Script,
    resume: ThousandeyesResumeConfig | None = None,
    incremental: bool = False,
    watermark: str | None = None,
) -> DriveResult:
    driver = SourceDriver(
        ThousandeyesSource(), ThousandeyesSourceConfig(api_token="fake-token", account_group_id="123")
    )
    return driver.run(
        name,
        script,
        resume_state=resume,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )


@pytest.mark.parametrize(("table", "alert_state"), [("active_alerts", "trigger"), ("cleared_alerts", "clear")])
@time_machine.travel("2026-06-01T12:00:00Z", tick=False)
def test_alert_states_and_window(table: str, alert_state: str) -> None:
    result = read(table, [ScriptedResponse(json={"alerts": [{"id": "alert-1"}]})])
    assert result.rows == [{"id": "alert-1"}]
    assert result.queries == [
        {
            "aid": ("123",),
            "state": (alert_state,),
            "startDate": ("2026-05-02T12:00:00Z",),
            "endDate": ("2026-06-01T12:00:00Z",),
        }
    ]
    assert result.requests[0].read_timeout == 60


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_start"),
    [
        (False, "2026-05-31T12:00:00Z", "2026-05-02T12:00:00Z"),
        (True, None, "2026-05-02T12:00:00Z"),
        (True, "2026-05-31T12:00:00Z", "2026-05-31T11:55:00Z"),
        (True, "2026-01-01T00:00:00Z", "2026-05-02T12:00:00Z"),
    ],
)
@time_machine.travel("2026-06-01T12:00:00Z", tick=False)
def test_results_fanout_keys_and_time_filter(incremental: bool, watermark: str | None, expected_start: str) -> None:
    row = {"roundId": 1780272000, "date": "2026-06-01T00:00:00Z", "agent": {"agentId": "5"}, "responseTime": 200}
    result = read(
        "http_server_results",
        [
            ScriptedResponse(
                json={"tests": [{"testId": "1"}, {"testId": "snapshot", "savedEvent": True}, {"testId": "2"}]}
            ),
            ScriptedResponse(json={"results": [row]}),
            ScriptedResponse(json={"results": [row]}),
        ],
        incremental=incremental,
        watermark=watermark,
    )
    assert result.rows == [{**row, "testId": "1", "agentId": "5"}, {**row, "testId": "2", "agentId": "5"}]
    assert result.paths == [
        "/v7/tests/http-server",
        "/v7/test-results/1/http-server",
        "/v7/test-results/2/http-server",
    ]
    for request in result.requests[1:]:
        assert request.query == {
            "aid": ("123",),
            "startDate": (expected_start,),
            "endDate": ("2026-06-01T12:00:00Z",),
        }
    assert result.saved_states[-1].paginator_state["completed"] == [
        "test-results/1/http-server",
        "test-results/2/http-server",
    ]
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.response.primary_keys == ["testId", "agentId", "roundId"]


@time_machine.travel("2026-06-02T12:00:00Z", tick=False)
def test_resume_child_page_keeps_original_window_and_skips_completed_tests() -> None:
    next_url = BASE + "test-results/2/http-server?aid=123&cursor=next"
    resume = ThousandeyesResumeConfig(
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-31T00:00:00Z",
        paginator_state={
            "completed": ["test-results/1/http-server"],
            "current": "test-results/2/http-server",
            "child_state": {"next_url": next_url},
        },
    )
    result = read(
        "http_server_results",
        [
            ScriptedResponse(json={"tests": [{"testId": "1"}, {"testId": "2"}, {"testId": "3"}]}),
            ScriptedResponse(json={"results": [{"roundId": 2, "agent": {"agentId": "5"}}]}),
            ScriptedResponse(json={"results": []}),
        ],
        resume=resume,
    )
    assert result.rows[0]["testId"] == "2"
    assert len(result.requests) == 3
    assert result.requests[1].url == next_url
    assert result.requests[2].param("startDate") == resume.start_date
    assert result.requests[2].param("endDate") == resume.end_date
    assert len(result.saved_states[-1].paginator_state["completed"]) == 3


@pytest.mark.parametrize("account_group_id", [None, "123"])
@pytest.mark.parametrize("status", [200, 401, 403])
def test_credential_validation_and_errors(account_group_id: str | None, status: int) -> None:
    source = ThousandeyesSource()
    answer = ScriptedResponse(
        status=status, json={"alerts": [], "_links": {"next": {"href": BASE + "alerts?cursor=unused"}}}
    )
    with scripted_network([answer]) as network:
        valid, message = source.validate_credentials(
            ThousandeyesSourceConfig(api_token="fake-token", account_group_id=account_group_id), 1
        )
    assert valid is (status == 200)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["authorization"] == "Bearer fake-token"
    assert request.query == ({"max": ("1",), "aid": ("123",)} if account_group_id else {"max": ("1",)})
    if status != 200:
        assert message == source.get_non_retryable_errors()[f"{status} Client Error"]
        result = read("tests", [ScriptedResponse(status=status, json={})])
        assert isinstance(result.raised, HTTPError)
        assert f"{status} Client Error" in str(result.raised)


@pytest.mark.parametrize("next_url", ["https://example.com/steal", "http://api.thousandeyes.com/v7/tests"])
def test_rejects_pagination_outside_api_origin(next_url: str) -> None:
    result = read(
        "tests", [ScriptedResponse(json={"tests": [{"testId": "1"}], "_links": {"next": {"href": next_url}}})]
    )
    assert isinstance(result.raised, ValueError)
    assert "Refusing to send request" in str(result.raised)
    assert len(result.requests) == 1


def test_redirects_are_not_followed() -> None:
    result = read("tests", [ScriptedResponse(status=302, headers={"Location": "https://example.com/steal"}, json={})])
    assert result.raised is not None
    assert [urlsplit(url).netloc for url in result.urls] == ["api.thousandeyes.com"]


def test_invalid_watermark_fails_before_request() -> None:
    result = read("http_server_results", [], incremental=True, watermark="not-a-date")
    assert isinstance(result.raised, ValueError)
    assert "Invalid ThousandEyes result timestamp" in str(result.raised)
    assert result.requests == []
