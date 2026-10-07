import json
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.arcade import (
    ArcadeResumeConfig,
    arcade_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.settings import (
    AUTH_ERROR,
    INSIGHTS_ERROR,
    PERMISSION_ERROR,
    PLAN_ERROR,
    PROVISIONING_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.source import ArcadeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.arcade import ArcadeSourceConfig


@pytest.fixture
def config() -> ArcadeSourceConfig:
    return ArcadeSourceConfig(api_key="fake-arcade-key", team_id="team-example", start_date="2025-01-01")


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with (
        Session() as session,
        patch.object(session, "send") as send,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        patch("time.sleep"),
        time_machine.travel("2025-02-01T00:00:00Z", tick=False),
    ):
        yield send


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://api.arcade.software/insights"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


def body(request: PreparedRequest) -> dict[str, Any]:
    assert isinstance(request.body, str | bytes)
    return json.loads(request.body)


def sync_items(source: SourceResponse) -> Iterable[list[dict[str, Any]]]:
    return cast(Iterable[list[dict[str, Any]]], source.items())


@pytest.mark.parametrize("resume_page", [None, 3])
def test_flow_pages_and_resume(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock, resume_page: int | None
) -> None:
    if resume_page:
        manager.can_resume.return_value = True
        manager.load_state.return_value = ArcadeResumeConfig(
            page=resume_page, period_start="2025-01-01T00:00:00+00:00", period_end="2025-01-31T00:00:00+00:00"
        )
    transport.side_effect = [
        response([{"flowId": "flow-one", "plays": 7}]),
        response([{"flowId": "flow-two", "plays": 9}]),
        response([]),
    ]
    source = arcade_source(config, "flow_engagement", 1, "job-example", manager)
    with activate_safe_point(lambda: None, covers_framework_checkpoints=True):
        pages = iter(sync_items(source))
        first = next(pages)
        assert manager.save_state.call_args.args[0].page == (resume_page or 1) + 1
        remaining = list(pages)
    rows = first + [row for page in remaining for row in page]
    assert [row["flowId"] for row in rows] == ["flow-one", "flow-two"]
    assert all(row["team_id"] == "team-example" for row in rows)
    requests = [call.args[0] for call in transport.call_args_list]
    start_page = resume_page or 1
    assert [body(request)["page"] for request in requests] == list(range(start_page, start_page + 3))
    expected_end = "2025-01-31T00:00:00+00:00" if resume_page else "2025-02-01T00:00:00+00:00"
    for request in requests:
        assert request.method == "POST"
        assert request.url == "https://api.arcade.software/insights"
        assert request.headers["Authorization"] == "fake-arcade-key"
        assert body(request) == {
            "type": "overviewPlays",
            "teamId": "team-example",
            "page": body(request)["page"],
            "size": 100,
            "from": "2025-01-01T00:00:00+00:00",
            "to": expected_end,
        }
    assert rows[0]["period_end"] == expected_end
    assert manager.save_state.call_args.args[0].completed


@pytest.mark.parametrize(
    ("name", "payload", "expected_rows", "method", "path", "expected_body"),
    [
        ("teams", {"success": True, "teams": [{"id": "team-one"}]}, [{"id": "team-one"}], "GET", "teams", None),
        ("users", {"success": True, "users": []}, [], "GET", "users", None),
        (
            "company_leads",
            [{"id": "company-one", "last7d": 5}],
            [{"id": "company-one", "last7d": 5, "team_id": "team-example"}],
            "POST",
            "insights",
            {"type": "companiesForLeads", "teamId": "team-example"},
        ),
    ],
)
def test_single_page_tables(
    config: ArcadeSourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    name: str,
    payload: object,
    expected_rows: list[dict[str, Any]],
    method: str,
    path: str,
    expected_body: dict[str, str] | None,
) -> None:
    transport.return_value = response(payload)
    source = arcade_source(config, name, 1, "job-example", manager)
    assert [row for page in sync_items(source) for row in page] == expected_rows
    transport.assert_called_once()
    request = transport.call_args.args[0]
    assert request.method == method
    assert request.url == f"https://api.arcade.software/{path}"
    assert request.headers["Authorization"] == "fake-arcade-key"
    assert (body(request) if request.body else None) == expected_body
    assert manager.save_state.call_args.args[0].completed


@pytest.mark.parametrize("name", ["teams", "flow_engagement"])
def test_completed_resume_does_not_repeat_rows(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock, name: str
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = ArcadeResumeConfig(
        page=1, period_start="2025-01-01T00:00:00+00:00", period_end="2025-01-31T00:00:00+00:00", completed=True
    )
    assert list(sync_items(arcade_source(config, name, 1, "job-example", manager))) == []
    transport.assert_not_called()


@pytest.mark.parametrize(
    ("status", "error", "message"),
    [
        (401, "Missing `authorization` header", AUTH_ERROR),
        (401, "Invalid API key", AUTH_ERROR),
        (401, "Workspace is not growth or above", PLAN_ERROR),
        (403, "This operation requires provisioning scope", PROVISIONING_ERROR),
        (403, "This operation requires insights scope", INSIGHTS_ERROR),
        (403, "Forbidden", PERMISSION_ERROR),
    ],
)
def test_auth_error_mapping(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock, status: int, error: str, message: str
) -> None:
    transport.return_value = response({"error": error}, status)
    assert validate_credentials(config, 1, "teams") == (False, message)
    transport.assert_called_once()
    with pytest.raises(ValueError) as raised:
        list(sync_items(arcade_source(config, "teams", 1, "job-example", manager)))
    assert str(raised.value) == message
    assert ArcadeSource().get_non_retryable_errors()[str(raised.value)] == message
    assert transport.call_count == 2


@pytest.mark.parametrize("status", [401, 403])
def test_create_accepts_missing_scope(config: ArcadeSourceConfig, transport: MagicMock, status: int) -> None:
    transport.return_value = response({"error": "This operation requires provisioning scope"}, status)
    valid, _ = validate_credentials(config, 1, None)
    assert valid == (status == 403)
    transport.assert_called_once()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock, status: int
) -> None:
    transport.side_effect = [response({"error": "Temporary failure"}, status), response({"teams": []})]
    assert list(sync_items(arcade_source(config, "teams", 1, "job-example", manager))) == []
    assert transport.call_count == 2


@pytest.mark.parametrize("start_date", ["not-a-date", "2025-02-30", "2026-01-01"])
def test_invalid_dates_do_not_send_requests(config: ArcadeSourceConfig, transport: MagicMock, start_date: str) -> None:
    config.start_date = start_date
    valid, message = validate_credentials(config, 1, None)
    assert not valid
    assert message and "date" in message
    transport.assert_not_called()


def test_unknown_table_does_not_send_requests(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock
) -> None:
    assert validate_credentials(config, 1, "unknown")[0] is False
    with pytest.raises(ValueError, match="Unknown Arcade table"):
        arcade_source(config, "unknown", 1, "job-example", manager)
    transport.assert_not_called()


def test_validation_uses_one_small_insights_page(config: ArcadeSourceConfig, transport: MagicMock) -> None:
    transport.return_value = response([{"flowId": "flow-one"}])
    assert validate_credentials(config, 1, "flow_engagement") == (True, None)
    transport.assert_called_once()
    assert body(transport.call_args.args[0])["size"] == 1


def test_missing_list_fails_instead_of_deleting_rows(
    config: ArcadeSourceConfig, manager: MagicMock, transport: MagicMock
) -> None:
    transport.return_value = response({"unexpected": []})
    with pytest.raises(ValueError):
        list(sync_items(arcade_source(config, "teams", 1, "job-example", manager)))
    manager.save_state.assert_not_called()
