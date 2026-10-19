import pytest

from requests.exceptions import HTTPError, Timeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onesignal import (
    OneSignalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.onesignal import OneSignalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.source import OneSignalSource

APP_ID = "11111111-2222-4333-8444-555555555555"
API_KEY = "test_onesignal_key"


def driver() -> SourceDriver:
    return SourceDriver(OneSignalSource(), OneSignalSourceConfig(app_id=APP_ID, api_key=API_KEY))


def test_notifications_walk_short_pages_and_stop_at_empty_page_with_cursor() -> None:
    result = driver().run(
        "notifications",
        [
            ScriptedResponse(
                json={"notifications": [{"id": "message-a", "successful": 12}], "next_time_offset": "YQ=="}
            ),
            ScriptedResponse(
                json={"notifications": [{"id": "message-b", "successful": 8}], "next_time_offset": "Yg=="}
            ),
            ScriptedResponse(json={"notifications": [], "next_time_offset": "Yg=="}),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "message-a", "successful": 12}, {"id": "message-b", "successful": 8}]
    assert result.paths == ["/notifications"] * 3
    assert result.params("time_offset") == ["1970-01-01T00:00:00.000Z", "YQ==", "Yg=="]
    assert result.params("offset") == [None] * 3
    assert result.params("app_id") == [APP_ID] * 3
    assert result.requests[0].headers["authorization"] == f"Key {API_KEY}"
    assert result.committed_states == [
        OneSignalResumeConfig(next_cursor="YQ=="),
        OneSignalResumeConfig(next_cursor="Yg=="),
    ]


def test_segments_use_app_path_and_offset_without_time_filter() -> None:
    first_page = [{"id": f"segment-{index}", "created_at": "2025-01-01T00:00:00Z"} for index in range(300)]
    result = driver().run(
        "segments",
        [
            ScriptedResponse(json={"segments": first_page, "total_count": 301}),
            ScriptedResponse(json={"segments": [{"id": "segment-last"}], "total_count": 301}),
        ],
    )

    assert result.raised is None
    assert result.rows == [*first_page, {"id": "segment-last"}]
    assert result.paths == [f"/apps/{APP_ID}/segments"] * 2
    assert result.params("offset") == ["0", "300"]
    assert result.params("time_offset") == [None, None]
    assert result.committed_states == [OneSignalResumeConfig(next_offset=300)]


@pytest.mark.parametrize(
    ("endpoint", "resume", "body", "param", "expected"),
    [
        (
            "notifications",
            OneSignalResumeConfig(next_cursor="YQ=="),
            {"notifications": [{"id": "message-last"}]},
            "time_offset",
            "YQ==",
        ),
        (
            "segments",
            OneSignalResumeConfig(next_offset=300),
            {"segments": [{"id": "segment-last"}], "total_count": 301},
            "offset",
            "300",
        ),
    ],
)
def test_resume_fetches_the_unwritten_page(
    endpoint: str, resume: OneSignalResumeConfig, body: dict[str, object], param: str, expected: str
) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json=body)], resume_state=resume)

    assert result.raised is None
    assert len(result.rows) == 1
    assert result.params(param) == [expected]


def test_notifications_reject_nonempty_pages_with_repeated_cursor() -> None:
    result = driver().run(
        "notifications",
        [ScriptedResponse(json={"notifications": [{"id": "message-a"}], "next_time_offset": "YQ=="})],
        resume_state=OneSignalResumeConfig(next_cursor="YQ=="),
    )

    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert result.rows == []


@pytest.mark.parametrize("endpoint", ["notifications", "segments"])
def test_missing_collection_fails_instead_of_replacing_table_with_empty_data(endpoint: str) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json={"errors": ["Unexpected response"]})])

    assert isinstance(result.raised, ValueError)
    assert result.rows == []


def test_failed_next_request_keeps_the_checkpoint_for_written_rows() -> None:
    result = driver().run(
        "notifications",
        [
            ScriptedResponse(json={"notifications": [{"id": "message-a"}], "next_time_offset": "YQ=="}),
            ScriptedResponse(status=401, json={"errors": ["Access denied"]}),
        ],
    )

    assert isinstance(result.raised, HTTPError)
    assert result.rows == [{"id": "message-a"}]
    assert result.committed_states == [OneSignalResumeConfig(next_cursor="YQ==")]


@pytest.mark.parametrize(
    ("response", "expected_message"),
    [
        (ScriptedResponse(json={"notifications": []}), None),
        (ScriptedResponse(status=400, json={"errors": ["App ID not found"]}), "OneSignal rejected these credentials."),
        (ScriptedResponse(status=401, json={"errors": ["Access denied"]}), "OneSignal rejected these credentials."),
        (ScriptedResponse(status=403, json={"errors": ["Access denied"]}), "OneSignal rejected these credentials."),
        (ScriptedResponse(status=404, json={"errors": ["Not found"]}), "OneSignal could not validate this connection."),
        (Timeout("request timed out"), "OneSignal could not validate this connection."),
        (ScriptedResponse(json={"unexpected": []}), "OneSignal could not validate this connection."),
        (ScriptedResponse(body=b"<html>Unavailable</html>"), "OneSignal could not validate this connection."),
        (
            ScriptedResponse(status=429, json={"errors": ["Rate limit exceeded"]}, headers={"Retry-After": "3600"}),
            "OneSignal could not validate this connection.",
        ),
    ],
)
def test_credential_probe_maps_vendor_failures_without_returning_response_data(
    response: ScriptedResponse | Timeout, expected_message: str | None
) -> None:
    config = OneSignalSourceConfig(app_id=APP_ID, api_key=API_KEY)
    with scripted_network([response] * 5) as network:
        valid, message = OneSignalSource().validate_credentials(config, team_id=1)

    assert valid is (expected_message is None)
    if expected_message is None:
        assert message is None
    else:
        assert message is not None and message.startswith(expected_message)
    request = network.requests_log[0]
    assert request.path == "/notifications"
    assert request.param("app_id") == APP_ID
    assert request.param("limit") == "1"
    assert request.headers["authorization"] == f"Key {API_KEY}"


def test_selected_table_credential_probe_reads_segments() -> None:
    config = OneSignalSourceConfig(app_id=APP_ID, api_key=API_KEY)
    with scripted_network([ScriptedResponse(json={"segments": []})]) as network:
        assert OneSignalSource().validate_credentials(config, team_id=1, schema_name="segments") == (True, None)

    assert network.requests_log[0].path == f"/apps/{APP_ID}/segments"
    assert network.requests_log[0].param("time_offset") is None
