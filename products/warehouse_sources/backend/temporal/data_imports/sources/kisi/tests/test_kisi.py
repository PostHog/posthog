from datetime import UTC, datetime, timedelta

import pytest

from requests.exceptions import ConnectionError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kisi import KisiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.kisi import (
    KisiEventSetError,
    KisiResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    AUTH_ERROR,
    EVENT_SET_CURSOR_ERROR,
    EVENT_SET_FAILED_ERROR,
    EVENTS_WINDOW,
    OFFSET_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.source import KisiSource


@pytest.fixture
def driver() -> SourceDriver:
    return SourceDriver(KisiSource(), KisiSourceConfig(api_key="test-key"))


@pytest.mark.parametrize("start_offset", [None, 100])
@pytest.mark.parametrize("last_page_size", [0, 1, 100])
@pytest.mark.parametrize("use_header", [False, True])
def test_pagination_and_resume(
    start_offset: int | None, last_page_size: int, use_header: bool, driver: SourceDriver
) -> None:
    offset = start_offset or 0
    first_page: list[dict[str, object]] = [{"id": offset + i} for i in range(100)]
    last_page: list[dict[str, object]] = [{"id": offset + 100 + i} for i in range(last_page_size)]
    total = offset + 100 + last_page_size
    pages = [
        ScriptedResponse(
            json=first_page,
            headers={"X-Collection-Range": f"{offset}-{offset + 99}/{total}"} if use_header else {},
        ),
        ScriptedResponse(
            json=last_page,
            headers={"X-Collection-Range": f"{offset + 100}-{offset + 199}/{total}"} if use_header else {},
        ),
        ScriptedResponse(json=[]),
    ]
    result = driver.run(
        "locks",
        pages,
        resume_state=KisiResumeConfig(offset=offset) if start_offset is not None else None,
    )

    expected_offsets = [offset]
    if not use_header or last_page_size:
        expected_offsets.append(offset + 100)
    if not use_header and last_page_size == 100:
        expected_offsets.append(offset + 200)
    assert result.raised is None
    assert result.rows == first_page + last_page
    assert result.params("offset") == [str(value) for value in expected_offsets]
    assert result.saved_states == [KisiResumeConfig(offset=value) for value in expected_offsets[1:]]


@pytest.mark.parametrize("total,should_fail", [(20_100, False), (20_101, True)])
def test_offset_limit_does_not_silently_truncate(total: int, should_fail: bool, driver: SourceDriver) -> None:
    rows: list[dict[str, object]] = [{"id": 20_000 + i} for i in range(100)]
    result = driver.run(
        "locks",
        [ScriptedResponse(json=rows, headers={"X-Collection-Range": f"20000-20099/{total}"})],
        resume_state=KisiResumeConfig(offset=20_000),
    )

    assert result.params("offset") == ["20000"]
    if should_fail:
        assert isinstance(result.raised, ValueError)
        assert OFFSET_ERROR in str(result.raised)
    else:
        assert result.raised is None
        assert result.items == [rows]


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors(status: int, message: str, driver: SourceDriver) -> None:
    result = driver.run("locks", [ScriptedResponse(status=status, json=[])])

    assert isinstance(result.raised, HTTPError)
    assert message in [
        text for pattern, text in KisiSource().get_non_retryable_errors().items() if pattern in str(result.raised)
    ]
    assert result.paths == ["/locks"]


@pytest.mark.parametrize(
    "status,message",
    [
        (200, None),
        (401, AUTH_ERROR),
        (403, PERMISSION_ERROR),
        (500, "Kisi could not validate the API key. Try again later."),
        (302, "Kisi returned an unexpected response. Try again later."),
    ],
)
def test_validate_credentials(status: int, message: str | None) -> None:
    response = ScriptedResponse(
        status=status,
        json=[],
        headers={"Location": "/redirected"} if status == 302 else {},
    )
    with scripted_network(always(response)) as network:
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (status == 200, message)

    assert {request.path for request in network.requests_log} == {"/user"}
    assert network.requests_log[0].url == "https://api.kisi.io/user"
    assert network.requests_log[0].headers["authorization"] == "KISI-LOGIN test-key"
    if status != 500:
        assert len(network.requests_log) == 1


def test_validate_connection_error() -> None:
    with scripted_network(always(ConnectionError("private detail"))) as network:
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (
            False,
            "Could not connect to Kisi. Try again later.",
        )

    assert {request.path for request in network.requests_log} == {"/user"}


def test_unsupported_table(driver: SourceDriver) -> None:
    result = driver.run("presences", [])

    assert isinstance(result.raised, ValueError)
    assert "Unsupported Kisi table" in str(result.raised)
    assert result.requests == []


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_set(set_id: int, status: str, events: list[dict[str, object]], cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"id": set_id, "status": status, "events": events, "cursor": cursor})


def test_roles_are_read_in_one_request(driver: SourceDriver) -> None:
    roles: list[dict[str, object]] = [{"id": f"role-{i}", "name": f"Role {i}"} for i in range(100)]
    result = driver.run("roles", [ScriptedResponse(json=roles)])

    assert result.raised is None
    assert result.rows == roles
    assert result.paths == ["/roles"]
    assert result.params("offset") == [None]


def test_events_walk_windows_from_the_watermark(driver: SourceDriver) -> None:
    watermark = (datetime.now(UTC) - timedelta(days=100)).replace(microsecond=0)
    first_page: list[dict[str, object]] = [{"uuid": "a"}, {"uuid": "b"}]
    second_page: list[dict[str, object]] = [{"uuid": "c"}]
    result = driver.run(
        "events",
        [
            _event_set(1, "in_progress", [], None),
            _event_set(1, "finished", first_page, "page-2"),
            _event_set(1, "finished", second_page, None),
            _event_set(2, "finished", [], None),
        ],
        incremental_field="created_at",
        db_incremental_field_last_value=watermark.isoformat(),
    )

    assert result.raised is None
    assert result.rows == first_page + second_page
    assert [(request.method, request.path) for request in result.requests] == [
        ("POST", "/event_sets"),
        ("GET", "/event_sets/1"),
        ("GET", "/event_sets/1"),
        ("POST", "/event_sets"),
    ]
    assert result.params("cursor") == [None, None, "page-2", None]
    intervals = [request.json()["event_set"]["interval"] for request in result.requests if request.method == "POST"]
    assert intervals[0] == f"{_timestamp(watermark)}/{_timestamp(watermark + EVENTS_WINDOW)}"
    assert intervals[1].startswith(f"{_timestamp(watermark + EVENTS_WINDOW)}/")
    assert (
        KisiResumeConfig(
            events_window_start=_timestamp(watermark),
            events_window_end=_timestamp(watermark + EVENTS_WINDOW),
            event_set_id=1,
            events_cursor="page-2",
            events_written=2,
        )
        in result.committed_states
    )


@pytest.mark.parametrize("expired", [False, True])
def test_events_resume_from_saved_event_set(expired: bool, driver: SourceDriver) -> None:
    window_start = (datetime.now(UTC) - timedelta(days=10)).replace(microsecond=0)
    window_end = window_start + timedelta(days=5)
    pages = [_event_set(7, "finished", [{"uuid": "b"}], None)]
    if expired:
        pages = [
            ScriptedResponse(status=404, json={"error": "Not found"}),
            _event_set(8, "finished", [{"uuid": "a"}, {"uuid": "b"}], None),
        ]
    result = driver.run(
        "events",
        [*pages, _event_set(9, "finished", [], None)],
        resume_state=KisiResumeConfig(
            events_window_start=_timestamp(window_start),
            events_window_end=_timestamp(window_end),
            event_set_id=7,
            events_cursor="page-3",
            events_written=1,
        ),
    )

    assert result.raised is None
    assert result.rows == [{"uuid": "b"}]
    assert result.requests[0].path == "/event_sets/7"
    assert result.requests[0].param("cursor") == "page-3"
    posts = [request.json()["event_set"]["interval"] for request in result.requests if request.method == "POST"]
    expected_posts = [f"{_timestamp(window_start)}/{_timestamp(window_end)}"] if expired else []
    assert posts[: len(expected_posts)] == expected_posts
    assert posts[len(expected_posts)].startswith(f"{_timestamp(window_end)}/")


@pytest.mark.parametrize(
    "pages,message",
    [
        ([_event_set(1, "in_progress", [], None), _event_set(1, "failed", [], None)], EVENT_SET_FAILED_ERROR),
        (
            [_event_set(1, "finished", [{"uuid": "a"}], "same"), _event_set(1, "finished", [], "same")],
            EVENT_SET_CURSOR_ERROR,
        ),
    ],
)
def test_events_errors_stop_the_window(pages: list[ScriptedResponse], message: str, driver: SourceDriver) -> None:
    result = driver.run("events", pages)

    assert isinstance(result.raised, KisiEventSetError)
    assert str(result.raised) == message
    if message == EVENT_SET_FAILED_ERROR:
        assert result.final_state.event_set_id is None
