from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.clevertap import ClevertapResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.settings import (
    CURSOR_ERROR,
    EXPORT_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.source import ClevertapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clevertap import (
    ClevertapSourceConfig,
)


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
