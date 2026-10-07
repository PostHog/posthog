from collections.abc import Callable, Generator
from datetime import date
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.acculynx import (
    AcculynxResumeConfig,
    DateWindow,
    appointment_range,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.source import AcculynxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class SyncSourceResponse(Protocol):
    primary_keys: list[str] | None

    def items(self) -> Generator[list[dict[str, Any]]]: ...


@pytest.mark.parametrize("name, offset_param", [("contacts", "pageStartIndex"), ("lead_sources", "recordStartIndex")])
def test_pagination_advances_by_returned_rows_and_stops_at_count(
    name: str,
    offset_param: str,
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        params = parse_qs(urlsplit(request.url or "").query)
        offset = int(params[offset_param][0])
        assert "startDate" not in params
        assert "since" not in params
        return response(request, {"count": 2, "pageSize": 25, "pageStartIndex": offset, "items": [{"id": str(offset)}]})

    http_send.side_effect = send
    assert list(pipeline(name).items()) == [[{"id": "0"}], [{"id": "1"}]]
    assert http_send.call_count == 2


@pytest.mark.parametrize(
    "body, status, error",
    [
        ({"count": 0, "pageSize": 25, "pageStartIndex": 0, "items": []}, 200, None),
        ({}, 416, None),
        ({"count": 1, "pageSize": 25, "pageStartIndex": 99, "items": [{"id": "one"}]}, 200, "unexpected page offset"),
        (
            {"count": 1, "pageSize": 0, "pageStartIndex": 0, "items": [{"id": "one"}]},
            200,
            "invalid pagination metadata",
        ),
        ({"error": "unexpected-envelope"}, 200, "selector"),
    ],
)
def test_empty_ranges_and_bad_envelopes_do_not_create_garbage_rows(
    body: dict[str, Any],
    status: int,
    error: str | None,
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    http_send.side_effect = lambda request, **_: response(request, body, status)
    if error:
        with pytest.raises(ValueError, match=error):
            list(pipeline("contacts").items())
    else:
        assert list(pipeline("contacts").items()) == []


def test_resume_stages_after_yield_and_replays_only_uncommitted_pages(
    pipeline: Callable[..., SyncSourceResponse],
    manager: ResumableSourceManager[AcculynxResumeConfig],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        params = parse_qs(urlsplit(request.url or "").query)
        offset = int(params["pageStartIndex"][0])
        return response(request, {"count": 3, "pageSize": 1, "pageStartIndex": offset, "items": [{"id": str(offset)}]})

    http_send.side_effect = send
    pages = iter(pipeline("contacts").items())
    assert next(pages) == [{"id": "0"}]
    manager.confirm()
    assert not manager.has_staged_state()
    assert next(pages) == [{"id": "1"}]
    manager.confirm()
    manager.commit()
    saved = manager.load_state()
    assert saved is not None and saved.paginator_state == {"offset": 1}
    pages.close()
    assert list(pipeline("contacts").items()) == [[{"id": "1"}], [{"id": "2"}]]
    manager.confirm()
    manager.commit()
    assert list(pipeline("contacts").items()) == []


def test_jobs_split_before_offset_cap_without_duplicate_boundary_rows(
    pipeline: Callable[..., SyncSourceResponse],
    manager: ResumableSourceManager[AcculynxResumeConfig],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    manager.save_state(AcculynxResumeConfig(windows=[["2025-01-01", "2025-01-02"]]))
    manager.confirm()
    manager.commit()
    attempts = 0

    def send(request: PreparedRequest, **_: Any) -> Response:
        nonlocal attempts
        attempts += 1
        params = parse_qs(urlsplit(request.url or "").query)
        assert params["sortBy"] == ["CreatedDate"]
        assert params["sortOrder"] == ["Ascending"]
        assert params["dateFilterType"] == ["CreatedDate"]
        assert params["recordStartIndex"] == ["0"]
        if attempts == 1:
            return response(request, {"count": 100_001, "pageSize": 25, "pageStartIndex": 0, "items": []})
        day = params["endDate"][0]
        items = [{"id": day, "createdDate": day + "T12:00:00Z"}]
        if day == "2025-01-02":
            items.insert(0, {"id": "2025-01-01", "createdDate": "2025-01-01T12:00:00Z"})
        return response(request, {"count": len(items), "pageSize": 25, "pageStartIndex": 0, "items": items})

    http_send.side_effect = send
    rows = [row for page in pipeline("jobs").items() for row in page]
    assert [row["id"] for row in rows] == ["2025-01-01", "2025-01-02"]
    assert attempts == 3


def test_unsplittable_job_day_fails_instead_of_truncating(
    pipeline: Callable[..., SyncSourceResponse],
    manager: ResumableSourceManager[AcculynxResumeConfig],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    manager.save_state(AcculynxResumeConfig(windows=[["2025-01-01", "2025-01-01"]]))
    manager.confirm()
    manager.commit()
    http_send.side_effect = lambda request, **_: response(
        request,
        {
            "count": 100_001,
            "pageSize": 25,
            "pageStartIndex": 0,
            "items": [],
        },
    )
    with pytest.raises(ValueError, match="AccuLynx job date window exceeds") as error:
        list(pipeline("jobs").items())
    assert any(pattern in str(error.value) for pattern in AcculynxSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    "name, parent, child, data",
    [
        ("estimates", "estimates", "estimates/parent-one", {"id": "child-one", "createdDate": "2025-01-01T00:00:00Z"}),
        ("financials", "jobs", "jobs/parent-one/financials", {"id": "child-one", "balanceDue": 100}),
        (
            "invoices",
            "jobs",
            "jobs/parent-one/invoices",
            {"count": 1, "pageSize": 25, "pageStartIndex": 0, "items": [{"id": "child-one"}]},
        ),
    ],
)
def test_child_rows_have_parent_keys_and_use_documented_selectors(
    name: str,
    parent: str,
    child: str,
    data: dict[str, Any],
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        path = urlsplit(request.url or "").path.removeprefix("/api/v2/")
        if path == parent:
            return response(
                request,
                {
                    "count": 1,
                    "pageSize": 25,
                    "pageStartIndex": 0,
                    "items": [
                        {"id": "parent-one", "createdDate": "2025-01-01T00:00:00Z"},
                    ],
                },
            )
        assert path == child
        return response(request, data)

    http_send.side_effect = send
    resource = pipeline(name)
    rows = [row for page in resource.items() for row in page]
    assert len(rows) == 1
    assert rows[0]["id"] == "child-one"
    assert rows[0]["estimate_id" if name == "estimates" else "job_id"] == "parent-one"
    assert resource.primary_keys and all(key in rows[0] for key in resource.primary_keys)


def test_payments_explode_each_group_without_parent_key_collisions(
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        path = urlsplit(request.url or "").path
        if path == "/api/v2/jobs":
            return response(
                request,
                {
                    "count": 2,
                    "pageSize": 25,
                    "pageStartIndex": 0,
                    "items": [
                        {"id": "job-one", "createdDate": "2025-01-01T00:00:00Z"},
                        {"id": "job-two", "createdDate": "2025-01-02T00:00:00Z"},
                    ],
                },
            )
        return response(
            request,
            {
                group: {"total": 10, group: [{"id": "payment-one", "amount": 10}]}
                for group in ("receivedPayments", "paidPayments", "additionalExpenses")
            },
        )

    http_send.side_effect = send
    resource = pipeline("payments")
    rows = [row for page in resource.items() for row in page]
    assert len(rows) == 6
    assert resource.primary_keys
    assert len({tuple(row[key] for key in resource.primary_keys) for row in rows}) == 6


def test_fanout_resume_skips_completed_parents_and_keeps_the_current_parent(
    pipeline: Callable[..., SyncSourceResponse],
    manager: ResumableSourceManager[AcculynxResumeConfig],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    child_paths = []

    def send(request: PreparedRequest, **_: Any) -> Response:
        path = urlsplit(request.url or "").path
        if path == "/api/v2/estimates":
            return response(
                request,
                {
                    "count": 3,
                    "pageSize": 25,
                    "pageStartIndex": 0,
                    "items": [{"id": f"estimate-{i}"} for i in range(3)],
                },
            )
        child_paths.append(path)
        return response(request, {"id": path.rsplit("/", 1)[1]})

    http_send.side_effect = send
    pages = iter(pipeline("estimates").items())
    assert next(pages)[0]["id"] == "estimate-0"
    assert next(pages)[0]["id"] == "estimate-1"
    manager.confirm()
    manager.commit()
    pages.close()
    child_paths.clear()
    rows = [row for page in pipeline("estimates").items() for row in page]
    assert [row["id"] for row in rows] == ["estimate-1", "estimate-2"]
    assert child_paths == ["/api/v2/estimates/estimate-1", "/api/v2/estimates/estimate-2"]


@pytest.mark.parametrize("status", [404, 416])
def test_missing_job_children_do_not_prevent_other_jobs_from_syncing(
    status: int,
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    def send(request: PreparedRequest, **_: Any) -> Response:
        path = urlsplit(request.url or "").path
        if path == "/api/v2/jobs":
            return response(
                request,
                {
                    "count": 2,
                    "pageSize": 25,
                    "pageStartIndex": 0,
                    "items": [{"id": f"job-{i}", "createdDate": "2025-01-01T00:00:00Z"} for i in range(2)],
                },
            )
        if path == "/api/v2/jobs/job-0/invoices":
            return response(request, {}, status)
        return response(request, {"count": 1, "pageSize": 25, "pageStartIndex": 0, "items": [{"id": "invoice-one"}]})

    http_send.side_effect = send
    assert list(pipeline("invoices").items()) == [[{"id": "invoice-one", "job_id": "job-1"}]]


def test_appointments_walk_bounded_date_windows_for_every_calendar(
    pipeline: Callable[..., SyncSourceResponse],
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    ranges = []

    def send(request: PreparedRequest, **_: Any) -> Response:
        path = urlsplit(request.url or "").path
        if path == "/api/v2/calendars":
            items = [{"id": "calendar-one"}, {"id": "calendar-two"}]
        else:
            params = parse_qs(urlsplit(request.url or "").query)
            start, end = params["startDate"][0], params["endDate"][0]
            assert (date.fromisoformat(end) - date.fromisoformat(start)).days < 90
            ranges.append((start, end))
            items = [{"id": "appointment-" + start}]
        return response(request, {"count": len(items), "pageSize": 25, "pageStartIndex": 0, "items": items})

    http_send.side_effect = send
    resource = pipeline("calendar_appointments", appointment_start_date="2025-01-01", appointment_end_date="2025-04-01")
    rows = [row for page in resource.items() for row in page]
    assert ranges == [("2025-01-01", "2025-03-31")] * 2 + [("2025-04-01", "2025-04-01")] * 2
    assert len(rows) == 4
    assert {row["calendar_id"] for row in rows} == {"calendar-one", "calendar-two"}


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_transport_retries_transient_statuses_and_classifies_auth_failures(
    status: int,
    monkeypatch: pytest.MonkeyPatch,
    http_send: MagicMock,
    response: Callable[..., Response],
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(RESTClient._send_request.retry, "sleep", delays.append)  # type: ignore[attr-defined]
    attempts = 0

    def send(request: PreparedRequest, **_: Any) -> Response:
        nonlocal attempts
        attempts += 1
        result = response(request, {"items": []}, status if attempts == 1 else 200)
        if status == 429:
            result.headers["Retry-After"] = "30"
        return result

    http_send.side_effect = send
    result, error = validate_credentials(
        "fake-key", "v2", "contacts", DateWindow(start=date(2025, 1, 1), end=date(2025, 1, 2))
    )
    assert result is (status >= 429)
    assert attempts == (2 if status >= 429 else 1)
    if status == 429:
        assert delays == [30]
    if status in (401, 403):
        request = http_send.call_args.args[0]
        with pytest.raises(HTTPError) as raised:
            response(request, {}, status).raise_for_status()
        assert any(pattern in str(raised.value) for pattern in AcculynxSource().get_non_retryable_errors())
        assert error


@time_machine.travel("2025-01-01T00:00:00Z", tick=False)
def test_optional_appointment_range_has_a_future_horizon() -> None:
    window = appointment_range(None, None)
    assert window.start == date(2000, 1, 1)
    assert window.end == date(2025, 4, 1)
