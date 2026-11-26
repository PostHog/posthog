import pytest

from requests.exceptions import HTTPError, Timeout

from products.warehouse_sources.sources.onesignal._config import OneSignalSourceConfig
from products.warehouse_sources.sources.onesignal.onesignal import OneSignalResumeConfig
from products.warehouse_sources.sources.onesignal.source import OneSignalSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network

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


@pytest.mark.parametrize(
    ("endpoint", "page_size", "path", "app_id_param"),
    [
        ("segments", 300, f"/apps/{APP_ID}/segments", None),
        ("templates", 50, "/templates", APP_ID),
    ],
)
def test_offset_endpoints_walk_to_total_count_without_time_filter(
    endpoint: str, page_size: int, path: str, app_id_param: str | None
) -> None:
    first_page = [{"id": f"{endpoint}-{index}", "created_at": "2025-01-01T00:00:00Z"} for index in range(page_size)]
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={endpoint: first_page, "total_count": page_size + 1}),
            ScriptedResponse(json={endpoint: [{"id": f"{endpoint}-last"}], "total_count": page_size + 1}),
        ],
    )

    assert result.raised is None
    assert result.rows == [*first_page, {"id": f"{endpoint}-last"}]
    assert result.paths == [path] * 2
    assert result.params("offset") == ["0", str(page_size)]
    assert result.params("limit") == [str(page_size)] * 2
    assert result.params("app_id") == [app_id_param] * 2
    assert result.params("time_offset") == [None, None]
    assert result.committed_states == [OneSignalResumeConfig(next_offset=page_size)]


def test_journeys_follow_next_cursor_until_it_is_omitted() -> None:
    result = driver().run(
        "journeys",
        [
            ScriptedResponse(json={"journeys": [{"id": "journey-a"}], "has_more": True, "next_cursor": "NTA="}),
            ScriptedResponse(json={"journeys": [{"id": "journey-b"}], "has_more": False}),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "journey-a"}, {"id": "journey-b"}]
    assert result.paths == [f"/apps/{APP_ID}/journeys"] * 2
    assert result.params("cursor") == [None, "NTA="]
    assert result.params("app_id") == [None, None]
    assert result.committed_states == [OneSignalResumeConfig(next_cursor="NTA=")]


def test_journey_stats_fan_out_over_every_journey_page_and_skip_deleted_journeys() -> None:
    stats_a = {"id": "journey-a", "started": 10, "completed": 8, "exited_early": 1, "nodes": {}, "branches": {}}
    stats_c = {"id": "journey-c", "started": 0, "completed": 0, "exited_early": 0, "nodes": {}, "branches": {}}
    result = driver().run(
        "journey_stats",
        [
            ScriptedResponse(
                json={"journeys": [{"id": "journey-a"}, {"id": "journey-b"}], "has_more": True, "next_cursor": "Mg=="}
            ),
            ScriptedResponse(json=stats_a),
            ScriptedResponse(status=404, json={"errors": [{"code": "journey-not-found"}]}),
            ScriptedResponse(json={"journeys": [{"id": "journey-c"}], "has_more": False}),
            ScriptedResponse(json=stats_c),
        ],
    )

    assert result.raised is None
    assert result.rows == [stats_a, stats_c]
    assert result.paths == [
        f"/apps/{APP_ID}/journeys",
        f"/apps/{APP_ID}/journeys/journey-a/stats",
        f"/apps/{APP_ID}/journeys/journey-b/stats",
        f"/apps/{APP_ID}/journeys",
        f"/apps/{APP_ID}/journeys/journey-c/stats",
    ]
    assert result.params("cursor") == [None, None, None, "Mg==", None]
    assert result.params("limit") == ["50", None, None, "50", None]


def test_journey_stats_resume_skips_journeys_already_written() -> None:
    stats_b = {"id": "journey-b", "started": 3, "completed": 1, "exited_early": 0, "nodes": {}, "branches": {}}
    completed_path = f"/apps/{APP_ID}/journeys/journey-a/stats"
    result = driver().run(
        "journey_stats",
        [
            ScriptedResponse(json={"journeys": [{"id": "journey-a"}, {"id": "journey-b"}]}),
            ScriptedResponse(json=stats_b),
        ],
        resume_state=OneSignalResumeConfig(
            fanout_state={"completed": [completed_path], "current": None, "child_state": None}
        ),
    )

    assert result.raised is None
    assert result.rows == [stats_b]
    assert result.paths == [f"/apps/{APP_ID}/journeys", f"/apps/{APP_ID}/journeys/journey-b/stats"]


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
        (
            "templates",
            OneSignalResumeConfig(next_offset=50),
            {"templates": [{"id": "template-last"}], "total_count": 51},
            "offset",
            "50",
        ),
        (
            "journeys",
            OneSignalResumeConfig(next_cursor="NTA="),
            {"journeys": [{"id": "journey-last"}]},
            "cursor",
            "NTA=",
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


@pytest.mark.parametrize("endpoint", ["notifications", "segments", "templates", "journeys", "journey_stats"])
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


@pytest.mark.parametrize(
    ("schema_name", "collection", "path", "app_id_param"),
    [
        ("segments", "segments", f"/apps/{APP_ID}/segments", None),
        ("templates", "templates", "/templates", APP_ID),
        ("journeys", "journeys", f"/apps/{APP_ID}/journeys", None),
        ("journey_stats", "journeys", f"/apps/{APP_ID}/journeys", None),
    ],
)
def test_selected_table_credential_probe_reads_that_table(
    schema_name: str, collection: str, path: str, app_id_param: str | None
) -> None:
    config = OneSignalSourceConfig(app_id=APP_ID, api_key=API_KEY)
    with scripted_network([ScriptedResponse(json={collection: []})]) as network:
        assert OneSignalSource().validate_credentials(config, team_id=1, schema_name=schema_name) == (True, None)

    assert network.requests_log[0].path == path
    assert network.requests_log[0].param("app_id") == app_id_param
    assert network.requests_log[0].param("time_offset") is None
