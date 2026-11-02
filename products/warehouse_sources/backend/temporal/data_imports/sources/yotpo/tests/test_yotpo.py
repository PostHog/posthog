from datetime import UTC, datetime

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yotpo import YotpoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.source import YotpoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.yotpo import YotpoResumeConfig


@pytest.mark.parametrize(
    ("endpoint", "envelope", "row", "size_param"),
    [
        ("reviews", "reviews", {"id": 1, "created_at": "2020-01-02T00:00:00Z", "deleted": True}, "count"),
        (
            "raw_data",
            "records",
            {"email_address": "person@example.com", "email_sent_timestamp": "2020-01-02T00:00:00Z"},
            "per_page",
        ),
        ("unsubscribers", "unsubscribers", {"user_email": "person@example.com", "email_type_id": 1}, "count"),
    ],
)
def test_paginated_tables_extract_rows_and_commit_the_next_page(
    endpoint: str, envelope: str, row: dict[str, object], size_param: str
) -> None:
    def page(rows: list[dict[str, object]]) -> ScriptedResponse:
        payload = {envelope: rows}
        return ScriptedResponse(json={"response": payload} if endpoint == "unsubscribers" else payload)

    until = datetime.now(UTC).date().isoformat()
    result = SourceDriver(
        YotpoSource(), YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01")
    ).run(
        endpoint,
        [ScriptedResponse(json={"access_token": "test-token"}), page([row]), page([row]), page([])],
    )

    assert result.raised is None
    assert result.rows == [row, row]
    assert result.requests[0].path == "/oauth/token"
    assert result.requests[0].json() == {
        "client_id": "test-store",
        "client_secret": "test-secret",
        "grant_type": "client_credentials",
    }
    assert result.params("page")[1:] == ["1", "2", "3"]
    assert result.params(size_param)[1:] == ["100", "100", "100"]
    assert all(request.headers["x-yotpo-token"] == "test-token" for request in result.requests[1:])
    assert result.committed_states == [YotpoResumeConfig(page=2, until=until), YotpoResumeConfig(page=3, until=until)]
    if endpoint == "reviews":
        assert result.params("deleted")[1:] == ["true", "true", "true"]
        assert result.params("since_date")[1:] == [None, None, None]
        assert result.paths[1:] == ["/v1/apps/test-store/reviews"] * 3
    elif endpoint == "raw_data":
        assert result.params("since")[1:] == ["2020-01-01"] * 3
        assert result.params("until")[1:] == [until] * 3
        assert result.params("sort")[1:] == [None] * 3
        assert result.paths[1:] == ["/analytics/v1/emails/test-store/export/raw_data"] * 3
    else:
        assert result.paths[1:] == ["/apps/test-store/unsubscribers"] * 3
    assert result.session_options[0]["capture"] is False
    assert "test-secret" in result.session_options[0]["redact_values"]
    assert "test-token" in result.session_options[1]["redact_values"]


def test_email_analytics_requests_daily_buckets_with_an_explicit_date_range() -> None:
    row = {"since": "2020-01-01", "until": "2020-01-01", "values": {"map": 4}}
    result = SourceDriver(
        YotpoSource(), YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01")
    ).run(
        "email_analytics",
        [ScriptedResponse(json={"access_token": "test-token"}), ScriptedResponse(json={"date_series_points": [row]})],
    )

    assert result.raised is None
    assert result.rows == [row]
    request = result.requests[1]
    assert request.path == "/analytics/v1/emails/test-store/emails_sent"
    assert request.param("token") == "test-token"
    assert request.param("date_bucket") == "day"
    assert request.param("group_by") == "email_type"
    assert request.param("since") == "2020-01-01"
    assert request.param("until") == datetime.now(UTC).date().isoformat()
    assert len(result.requests) == 2


def test_resume_preserves_the_email_window_and_skips_written_pages() -> None:
    resume = YotpoResumeConfig(page=4, until="2020-02-01")
    result = SourceDriver(
        YotpoSource(), YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01")
    ).run(
        "raw_data",
        [ScriptedResponse(json={"access_token": "test-token"}), ScriptedResponse(json={"records": []})],
        resume_state=resume,
    )
    assert result.raised is None
    assert result.requests[1].param("page") == "4"
    assert result.requests[1].param("until") == "2020-02-01"


def test_a_failed_next_page_keeps_the_cursor_of_the_written_batch() -> None:
    result = SourceDriver(
        YotpoSource(), YotpoSourceConfig(app_key="test-store", api_secret="test-secret", start_date="2020-01-01")
    ).run(
        "reviews",
        [
            ScriptedResponse(json={"access_token": "test-token"}),
            ScriptedResponse(json={"reviews": [{"id": 1}]}),
            ScriptedResponse(status=403, json={}),
        ],
    )
    assert isinstance(result.raised, HTTPError)
    assert result.rows == [{"id": 1}]
    assert result.committed_states == [YotpoResumeConfig(page=2, until=datetime.now(UTC).date().isoformat())]
