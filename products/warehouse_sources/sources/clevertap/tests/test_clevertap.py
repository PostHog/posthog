from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.clevertap._config import ClevertapSourceConfig
from products.warehouse_sources.sources.clevertap.clevertap import ClevertapResumeConfig
from products.warehouse_sources.sources.clevertap.settings import CURSOR_ERROR, EXPORT_ERROR
from products.warehouse_sources.sources.clevertap.source import ClevertapSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def driver() -> SourceDriver:
    return SourceDriver(
        ClevertapSource(),
        ClevertapSourceConfig(
            account_id="TEST-ACCOUNT",
            passcode="fake-passcode",
            region="in1",
            event_name="Product Viewed",
            start_date="2024-01-01",
        ),
    )


@pytest.mark.parametrize("endpoint", ["events", "profiles"])
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_two_step_pagination_keeps_terminal_rows_and_commits_each_checkpoint(endpoint: str) -> None:
    first = {"ts": 20240101121212, "identity": "fake-user", "profileData": {"color": "blue"}}
    last = {"ts": 20240102121212, "platformInfo": []}
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"status": "success", "cursor": "initial%2Fcursor"}),
            ScriptedResponse(json={"status": "success", "records": [first, first], "next_cursor": "next+cursor"}),
            ScriptedResponse(json={"status": "success", "records": [last]}),
        ],
    )
    assert result.raised is None
    assert [request.method for request in result.requests] == ["POST", "GET", "GET"]
    assert result.requests[0].json() == {"event_name": "Product Viewed", "from": 20240101, "to": 20240103}
    assert result.requests[0].param("app") == "true"
    assert result.requests[0].param("profile") == "true"
    assert result.requests[0].param("events") == "true"
    assert result.params("cursor") == [None, "initial%2Fcursor", "next+cursor"]
    for request in result.requests:
        assert request.origin == "https://in1.api.clevertap.com"
        assert request.path == f"/1/{endpoint}.json"
        assert request.headers["x-clevertap-account-id"] == "TEST-ACCOUNT"
        assert request.headers["x-clevertap-passcode"] == "fake-passcode"
    for request in result.requests[1:]:
        assert request.json() is None
        assert "content-type" not in request.headers
        assert set(request.query) == {"cursor"}
    assert len(result.rows) == 3
    assert result.rows[0] == result.rows[1]
    assert result.rows[2]["platformInfo"] == []
    if endpoint == "events":
        assert [row["event_date"] for row in result.rows] == ["2024-01-01", "2024-01-01", "2024-01-02"]
        assert result.rows[0]["event_name"] == "Product Viewed"
        assert result.rows[0]["ts"] == 20240101121212
    else:
        assert result.rows == [first, first, last]
    assert result.committed_states == [
        ClevertapResumeConfig(cursor="initial%2Fcursor"),
        ClevertapResumeConfig(cursor="next+cursor"),
        ClevertapResumeConfig(cursor=None, completed=True),
    ]


@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_resume_skips_cursor_creation_and_preserves_last_page_checkpoint_on_failure() -> None:
    result = driver().run(
        "profiles",
        [
            ScriptedResponse(
                json={"status": "success", "records": [{"identity": "fake-user"}], "next_cursor": "later"}
            ),
            ScriptedResponse(status=400, json={"status": "fail", "error": "Invalid cursor", "code": 4004}),
        ],
        resume_state=ClevertapResumeConfig(cursor="saved"),
    )
    assert [request.method for request in result.requests] == ["GET", "GET"]
    assert result.params("cursor") == ["saved", "later"]
    assert result.rows == [{"identity": "fake-user"}]
    assert result.committed_states == [ClevertapResumeConfig(cursor="later")]
    assert str(result.raised) == CURSOR_ERROR


@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_completed_resume_makes_no_requests() -> None:
    result = driver().run("events", [], resume_state=ClevertapResumeConfig(cursor=None, completed=True))
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []


@pytest.mark.parametrize("terminal", [{"status": "success"}, {"status": "success", "records": []}])
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_empty_page_with_cursor_continues_until_terminal_response(terminal: dict[str, Any]) -> None:
    result = driver().run(
        "events",
        [
            ScriptedResponse(json={"status": "success", "cursor": "first"}),
            ScriptedResponse(json={"status": "success", "records": [], "next_cursor": "last"}),
            ScriptedResponse(json=terminal),
        ],
    )
    assert result.raised is None
    assert result.params("cursor") == [None, "first", "last"]
    assert result.committed_states[-1] == ClevertapResumeConfig(cursor=None, completed=True)


@pytest.mark.parametrize(
    "pending",
    [
        {"status": "fail", "error": "Request still in progress, please retry later", "code": 2},
        {"status": "fail", "error": "Too many requests"},
        {"status": "fail", "error": "System busy, please retry later"},
    ],
)
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_body_errors_retry_the_same_cursor_without_losing_rows(pending: dict[str, Any]) -> None:
    result = driver().run(
        "profiles",
        [
            ScriptedResponse(json=pending),
            ScriptedResponse(json={"status": "success", "records": [{"identity": "fake-user"}]}),
        ],
        resume_state=ClevertapResumeConfig(cursor="saved"),
    )
    assert result.raised is None
    assert result.params("cursor") == ["saved", "saved"]
    assert result.rows == [{"identity": "fake-user"}]


@pytest.mark.parametrize(
    ("body", "message", "resume"),
    [
        ({"status": "fail", "error": "Unexpected export failure"}, EXPORT_ERROR, True),
        ({"status": "CURSOR_INVALIDATED"}, CURSOR_ERROR, True),
        ({"status": "success"}, "CleverTap did not return an export cursor.", False),
        ({"status": "success", "records": None}, "CleverTap returned an invalid records list.", True),
        ({"status": "success", "records": [1]}, "CleverTap returned an invalid records list.", True),
        ({"status": "success", "next_cursor": 42}, "CleverTap returned an invalid export cursor.", True),
    ],
)
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_bad_response_fails_without_committing_completion(body: dict[str, Any], message: str, resume: bool) -> None:
    result = driver().run(
        "profiles",
        [ScriptedResponse(json=body)],
        resume_state=ClevertapResumeConfig(cursor="saved") if resume else None,
    )
    assert str(result.raised) == message
    assert result.rows == []
    assert result.saved_states == []


@time_machine.travel("2024-03-05T12:00:00Z", tick=False)
def test_campaigns_walk_31_day_windows_and_resume_from_the_next_window() -> None:
    result = driver().run(
        "campaigns",
        [
            ScriptedResponse(json={"status": "success", "targets": [{"id": 1, "status": "completed"}]}),
            ScriptedResponse(json={"status": "success", "targets": []}),
            ScriptedResponse(json={"status": "success", "targets": [{"id": 2, "status": "pending"}]}),
        ],
    )
    assert result.raised is None
    assert [request.path for request in result.requests] == ["/1/targets/list.json"] * 3
    assert [request.json() for request in result.requests] == [
        {"from": 20240101, "to": 20240131},
        {"from": 20240201, "to": 20240302},
        {"from": 20240303, "to": 20240304},
    ]
    assert [row["id"] for row in result.rows] == [1, 2]
    assert result.committed_states[-1] == ClevertapResumeConfig(cursor=None, completed=True)

    resumed = driver().run(
        "campaigns",
        [ScriptedResponse(json={"status": "success", "targets": []})],
        resume_state=ClevertapResumeConfig(cursor=None, window_from="2024-03-03"),
    )
    assert [request.json() for request in resumed.requests] == [{"from": 20240303, "to": 20240304}]


@pytest.mark.parametrize(
    ("resume", "expected_reports"),
    [
        (None, [1, 3]),
        (ClevertapResumeConfig(cursor=None, window_from="2024-01-01", campaign_id=1), [3]),
    ],
)
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_campaign_reports_fan_out_over_completed_campaigns(
    resume: ClevertapResumeConfig | None, expected_reports: list[int]
) -> None:
    campaigns = [
        {"id": 1, "name": "First", "scheduled_on": 202401011200, "status": "completed"},
        {"id": 2, "name": "Running", "scheduled_on": 202401021200, "status": "running"},
        {"id": 3, "name": "Deleted", "scheduled_on": 202401031200, "status": "completed"},
    ]
    reports = {
        1: ScriptedResponse(json={"status": "success", "result": {"sent": 82, "clicked": 28}}),
        3: ScriptedResponse(status=404, json={"status": "fail", "error": "Report not found", "code": 404}),
    }
    result = driver().run(
        "campaign_reports",
        [
            ScriptedResponse(json={"status": "success", "targets": campaigns}),
            *[reports[campaign_id] for campaign_id in expected_reports],
        ],
        resume_state=resume,
    )
    assert result.raised is None
    assert result.requests[0].json() == {"from": 20240101, "to": 20240103}
    assert [request.json() for request in result.requests[1:]] == [{"id": i} for i in expected_reports]
    assert {request.path for request in result.requests[1:]} == {"/1/targets/result.json"}
    expected_rows = (
        [{"sent": 82, "clicked": 28, "campaign_id": 1, "campaign_name": "First", "scheduled_on": 202401011200}]
        if 1 in expected_reports
        else []
    )
    assert result.rows == expected_rows
    assert result.committed_states[-1] == ClevertapResumeConfig(cursor=None, window_from="2024-01-01", campaign_id=3)


@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_message_reports_request_the_whole_range_and_rename_the_message_id() -> None:
    message = {"message id": 1508323121, "data": [[{"sent": 0}]], "status": "completed", "channel": "InApp"}
    result = driver().run("message_reports", [ScriptedResponse(json={"status": "success", "messages": [message]})])
    assert result.raised is None
    assert result.requests[0].path == "/1/message/report.json"
    assert result.requests[0].json() == {"from": "20240101", "to": "20240103", "daily": False}
    assert result.rows == [
        {"data": [[{"sent": 0}]], "status": "completed", "channel": "InApp", "message_id": 1508323121}
    ]


@time_machine.travel("2024-04-04T12:00:00Z", tick=False)
def test_content_blocks_page_until_the_total() -> None:
    result = driver().run(
        "content_blocks",
        [
            ScriptedResponse(json={"status": "success", "contentBlocks": [{"id": 1}], "total": 101}),
            ScriptedResponse(json={"status": "success", "contentBlocks": [{"id": 2}], "total": 101}),
        ],
    )
    assert result.raised is None
    assert [request.method for request in result.requests] == ["GET", "GET"]
    assert result.params("pageNumber") == ["1", "2"]
    assert result.params("pageSize") == ["100", "100"]
    assert result.rows == [{"id": 1}, {"id": 2}]
    assert result.committed_states == [
        ClevertapResumeConfig(cursor=None, page=2),
        ClevertapResumeConfig(cursor=None, completed=True),
    ]
