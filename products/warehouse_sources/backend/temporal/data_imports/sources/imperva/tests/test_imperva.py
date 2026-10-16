from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

import requests_mock
from requests import HTTPError, Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imperva import (
    ImpervaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.imperva import (
    ImpervaAPIError,
    ImpervaAuth,
    ImpervaResumeConfig,
    make_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.settings import DAY_MS
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.source import ImpervaSource

SITES_URL = "https://api.imperva.com/sites-mgmt/v3/sites"
STATS_URL = "https://my.imperva.com/api/stats/v1"
CONFIG = ImpervaSourceConfig(api_id="fake-api-id", api_key="fake-api-key", account_id="12345")
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
TODAY = int(NOW.replace(hour=0).timestamp() * 1000)


@pytest.mark.parametrize("resume_page", [None, 4])
@pytest.mark.parametrize("has_total_pages", [False, True])
def test_sites_pagination_and_resume(resume_page: int | None, has_total_pages: bool) -> None:
    first_page = resume_page or 0
    metadata = {"meta": {"totalPages": first_page + 2}} if has_total_pages else {}
    result = SourceDriver(ImpervaSource(), CONFIG).run(
        "sites",
        [
            ScriptedResponse(json={"data": [{"id": 10, "name": "example.com"}], **metadata}),
            ScriptedResponse(json={"data": [{"id": 11, "name": "example.org"}], **metadata}),
            ScriptedResponse(json={"data": []}),
        ],
        resume_state=ImpervaResumeConfig(page=resume_page) if resume_page is not None else None,
    )

    assert result.raised is None
    assert result.items == [
        [{"id": 10, "name": "example.com"}],
        [{"id": 11, "name": "example.org"}],
    ]
    page_count = 2 if has_total_pages else 3
    assert result.paths == ["/sites-mgmt/v3/sites"] * page_count
    assert result.params("page") == [str(first_page + offset) for offset in range(page_count)]
    for request in result.requests:
        assert request.method == "GET"
        assert request.headers["x-api-id"] == "fake-api-id"
        assert request.headers["x-api-key"] == "fake-api-key"
        assert request.param("caid") == "12345"
        assert request.param("size") == "100"
        assert "fake-api" not in request.url
    assert result.saved_states == [ImpervaResumeConfig(page=first_page + offset) for offset in range(1, page_count)]


@pytest.mark.parametrize("name", ["visits_timeseries", "hits_timeseries", "bandwidth_timeseries"])
@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_start"),
    [
        (False, TODAY - 2 * DAY_MS, TODAY - 90 * DAY_MS),
        (True, None, TODAY - 90 * DAY_MS),
        (True, TODAY - 2 * DAY_MS + 1000, TODAY - 3 * DAY_MS),
        (True, TODAY - 120 * DAY_MS, TODAY - 90 * DAY_MS),
    ],
)
@time_machine.travel(NOW, tick=False)
def test_stats_request_window_and_series_rows(
    name: str, incremental: bool, watermark: int | None, expected_start: int
) -> None:
    result = SourceDriver(ImpervaSource(), CONFIG).run(
        name,
        [
            ScriptedResponse(
                json={
                    "res": 0,
                    name: [
                        {"id": "human", "name": "Human", "data": [[TODAY, 12], [TODAY - DAY_MS, 0]]},
                        {"id": "bot", "name": "Bot", "data": [[TODAY, 4]]},
                    ],
                }
            )
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == [
        [
            {"account_id": "12345", "id": "human", "name": "Human", "timestamp": TODAY, "value": 12},
            {"account_id": "12345", "id": "human", "name": "Human", "timestamp": TODAY - DAY_MS, "value": 0},
            {"account_id": "12345", "id": "bot", "name": "Bot", "timestamp": TODAY, "value": 4},
        ]
    ]
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.response.supports_resume is False
    assert len({tuple(row[key] for key in result.response.primary_keys or []) for row in result.rows}) == 3
    assert len(result.requests) == 1
    assert result.requests[0].method == "POST"
    assert result.paths == ["/api/stats/v1"]
    assert result.queries == [
        {
            "account_id": ("12345",),
            "time_range": ("custom",),
            "start": (str(expected_start),),
            "end": (str(int(NOW.timestamp() * 1000)),),
            "granularity": (str(DAY_MS),),
            "stats": (name,),
        }
    ]
    assert result.saved_states == []


@pytest.mark.parametrize("code", [9403, 9411, 9413, 9414, 9415, 2, 13001, 13002, 9999])
def test_body_errors_never_become_empty_syncs(code: int) -> None:
    with requests_mock.Mocker() as http:
        http.post(
            STATS_URL, json={"res": code, "res_message": "Authentication missing or invalid", "hits_timeseries": []}
        )
        with pytest.raises(ImpervaAPIError) as error:
            list(make_resource(CONFIG, "hits_timeseries", api_version="v3", team_id=1, job_id="test"))
        assert error.value.code == code
        assert http.call_count == 1
        if code != 9999:
            assert any(pattern in str(error.value) for pattern in ImpervaSource().get_non_retryable_errors())


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_errors_are_terminal(status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(SITES_URL, status_code=status, json={})
        with pytest.raises(HTTPError) as error:
            list(make_resource(CONFIG, "sites", api_version="v3", team_id=1, job_id="test"))
        assert any(pattern in str(error.value) for pattern in ImpervaSource().get_non_retryable_errors())
        assert http.call_count == 1


@pytest.mark.parametrize(("status", "body"), [(429, {}), (503, {}), (200, {"res": 1}), (200, {"res": 4})])
def test_transient_errors_are_retried(status: int, body: dict[str, Any]) -> None:
    with requests_mock.Mocker() as http, patch("tenacity.nap.time.sleep"):
        http.post(STATS_URL, [{"status_code": status, "json": body}, {"json": {"res": 0, "hits_timeseries": []}}])
        assert list(make_resource(CONFIG, "hits_timeseries", api_version="v3", team_id=1, job_id="test")) == []
        assert http.call_count == 2


@pytest.mark.parametrize("body", [{"res": 0}, {"sites": []}, {"res": 0, "hits_timeseries": {}}])
def test_malformed_response_fails(body: dict[str, Any]) -> None:
    with requests_mock.Mocker() as http:
        http.post(STATS_URL, json=body)
        with pytest.raises(ValueError):
            list(make_resource(CONFIG, "hits_timeseries", api_version="v3", team_id=1, job_id="test"))


def test_auth_registers_both_secrets_for_redaction() -> None:
    auth = ImpervaAuth(CONFIG)
    request = Request("POST", SITES_URL, auth=auth).prepare()
    assert request.headers["x-API-Id"] in auth.secret_values()
    assert request.headers["x-API-Key"] in auth.secret_values()


def test_unknown_table_fails_before_network() -> None:
    with requests_mock.Mocker() as http, pytest.raises(ValueError, match="Unknown Imperva table"):
        make_resource(CONFIG, "missing", api_version="v3", team_id=1, job_id="test")
    assert http.call_count == 0
