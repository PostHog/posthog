import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.sequenzy._config import SequenzySourceConfig
from products.warehouse_sources.sources.sequenzy.sequenzy import SequenzyResumeConfig, validate_credentials
from products.warehouse_sources.sources.sequenzy.source import SequenzySource


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


NOW = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def frozen_now() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def _drive(
    endpoint: str,
    responses: Any,
    resume: SequenzyResumeConfig | None = None,
    company_id: str | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(SequenzySource(), SequenzySourceConfig(api_key="test-key", company_id=company_id))
    return driver.run(endpoint, responses, resume_state=resume, **inputs)


def _incremental(last_value: dt.datetime) -> dict[str, Any]:
    return {"should_use_incremental_field": True, "db_incremental_field_last_value": last_value}


def _offset_page(selector: str, rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return _make_http_response({"success": True, selector: rows, "pagination": {"total": total}})


def _numbered_page(selector: str, rows: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return _make_http_response({"success": True, selector: rows, "pagination": {"totalPages": total_pages}})


class TestSequenzyPagination:
    def test_campaigns_offset_pagination_stops_at_total(self) -> None:
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100)],
                    "pagination": {"limit": 100, "offset": 0, "count": 100, "total": 150, "hasMore": True},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100, 150)],
                    "pagination": {"limit": 100, "offset": 100, "count": 50, "total": 150, "hasMore": False},
                }
            ),
        ]
        result = _drive("campaigns", responses)

        assert [(request.param("offset"), request.param("limit")) for request in result.requests] == [
            ("0", "100"),
            ("100", "100"),
        ]
        assert len(result.rows) == 150


class TestSequenzyFanOut:
    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "parent_selector", "child_prefix", "parent_key"),
        [
            ("campaign_events", "/campaigns", "campaigns", "/metrics/campaigns", "campaignId"),
            ("sequence_events", "/sequences", "sequences", "/metrics/sequences", "sequenceId"),
        ],
    )
    def test_events_walk_every_parent_and_page_with_all_event_types(
        self, endpoint: str, parent_path: str, parent_selector: str, child_prefix: str, parent_key: str
    ) -> None:
        script = route(
            {
                parent_path: [_offset_page(parent_selector, [{"id": "p1"}, {"id": "p2"}], total=2)],
                f"{child_prefix}/p1/events": [
                    _numbered_page("events", [{"id": "e1", "campaignId": "node_1"}], total_pages=2),
                    _numbered_page("events", [{"id": "e2", "campaignId": "node_1"}], total_pages=2),
                ],
                f"{child_prefix}/p2/events": [_numbered_page("events", [], total_pages=0)],
            }
        )
        result = _drive(endpoint, script)

        assert result.raised is None
        child_requests = [r for r in result.requests if r.path.endswith("/events")]
        assert [(r.path.split("/")[-2], r.param("page")) for r in child_requests] == [
            ("p1", "1"),
            ("p1", "2"),
            ("p2", "1"),
        ]
        assert {r.param("eventTypes") for r in child_requests} == {
            "send,delivery,bounce,complaint,open,click,unsubscribe,delivery_delay,transport_failure"
        }
        assert {(r.param("start"), r.param("end"), r.param("period")) for r in child_requests} == {
            ("2026-03-17T13:00:00.000Z", "2026-06-15T12:00:00.000Z", None)
        }
        assert {r.param("limit") for r in child_requests} == {"500"}
        assert [(row["id"], row[parent_key]) for row in result.rows] == [("e1", "p1"), ("e2", "p1")]

    def test_enrollments_page_by_offset_with_every_status(self) -> None:
        script = route(
            {
                "/sequences": [_offset_page("sequences", [{"id": "seq_1"}], total=1)],
                "/sequences/seq_1/enrollments": [
                    _offset_page("enrollments", [{"enrollmentId": f"tok_{i}"} for i in range(500)], total=501),
                    _offset_page("enrollments", [{"enrollmentId": "tok_500"}], total=501),
                ],
            }
        )
        result = _drive("sequence_enrollments", script)

        assert result.raised is None
        child_requests = [r for r in result.requests if r.path.endswith("/enrollments")]
        assert [(r.param("offset"), r.param("limit")) for r in child_requests] == [("0", "500"), ("500", "500")]
        assert {r.param("status") for r in child_requests} == {"active,waiting,paused,completed,failed,cancelled"}
        assert {r.param("sort") for r in child_requests} == {"enrolled_at_asc"}
        assert len(result.rows) == 501
        assert {row["sequenceId"] for row in result.rows} == {"seq_1"}

    def test_resumed_events_run_keeps_the_original_time_range(self) -> None:
        last_value = NOW - dt.timedelta(days=1)

        def script() -> Any:
            return route(
                {
                    "/campaigns": [_offset_page("campaigns", [{"id": "c1"}], total=1)] * 2,
                    "/metrics/campaigns/c1/events": [
                        _numbered_page("events", [{"id": "e1"}], total_pages=2),
                        _numbered_page("events", [{"id": "e2"}], total_pages=2),
                    ],
                }
            )

        first = _drive("campaign_events", script(), **_incremental(last_value))
        checkpoint = first.committed_states[0]

        with time_machine.travel(NOW + dt.timedelta(hours=3), tick=False):
            resumed = _drive("campaign_events", script(), resume=checkpoint, **_incremental(last_value))

        resumed_child = [r for r in resumed.requests if r.path.endswith("/events")]
        assert resumed_child[0].param("page") == "2"
        assert resumed_child[0].param("end") == "2026-06-15T12:00:00.000Z"


class TestSequenzyTimeFilter:
    @pytest.mark.parametrize(
        "inputs",
        [
            {},
            _incremental(NOW - dt.timedelta(minutes=5)),
        ],
    )
    def test_email_sends_read_the_whole_retained_window(self, inputs: dict[str, Any]) -> None:
        result = _drive("email_sends", [_numbered_page("emailSends", [{"id": "s1"}], total_pages=1)], **inputs)

        request = result.requests[0]
        assert request.param("days") == "14"
        assert (request.param("sortField"), request.param("sortOrder")) == ("createdAt", "asc")

    @pytest.mark.parametrize(
        ("last_value", "expected_start"),
        [
            (NOW - dt.timedelta(days=1), "2026-06-14T12:00:00.000Z"),
            ("2026-06-14T12:00:00Z", "2026-06-14T12:00:00.000Z"),
            (NOW - dt.timedelta(days=200), "2026-03-17T13:00:00.000Z"),
        ],
    )
    def test_incremental_events_send_a_bounded_range(self, last_value: Any, expected_start: str) -> None:
        script = route(
            {
                "/campaigns": [_offset_page("campaigns", [{"id": "c1"}], total=1)],
                "/metrics/campaigns/c1/events": [_numbered_page("events", [], total_pages=0)],
            }
        )
        result = _drive("campaign_events", script, **_incremental(last_value))

        child = next(r for r in result.requests if r.path.endswith("/events"))
        assert (child.param("start"), child.param("end"), child.param("period")) == (
            expected_start,
            "2026-06-15T12:00:00.000Z",
            None,
        )


class TestSequenzyResume:
    @pytest.mark.parametrize(
        ("endpoint", "resume", "param", "expected"),
        [
            ("subscribers", SequenzyResumeConfig(cursor="cur_saved"), "cursor", "cur_saved"),
            ("campaigns", SequenzyResumeConfig(offset=100), "offset", "100"),
            ("email_metrics", SequenzyResumeConfig(page=2), "page", "2"),
            ("email_sends", SequenzyResumeConfig(page=3), "page", "1"),
        ],
    )
    def test_resume_seeds_first_request(
        self, endpoint: str, resume: SequenzyResumeConfig, param: str, expected: Any
    ) -> None:
        selector = {
            "subscribers": "subscribers",
            "campaigns": "campaigns",
            "email_metrics": "emails",
            "email_sends": "emailSends",
        }[endpoint]
        responses = [
            _make_http_response({"success": True, selector: [], "pagination": {"nextCursor": None}}),
        ]
        result = _drive(endpoint, responses, resume)

        assert result.requests[0].param(param) == expected


class TestSequenzyCompanyHeader:
    def test_company_id_sets_workspace_header(self) -> None:
        responses = [
            _make_http_response({"success": True, "tags": []}),
        ]
        result = _drive("tags", responses, company_id="company_abc123")

        assert result.requests[0].headers["x-company-id"] == "company_abc123"


class TestValidateCredentials:
    def test_company_id_forwarded_as_header(self) -> None:
        with scripted_network(always(_make_http_response({}, status_code=200))) as network:
            validate_credentials("seq_user_key", company_id="company_abc123")

        assert network.requests_log[0].headers["x-company-id"] == "company_abc123"

    def test_non_ascii_key_returns_actionable_message_without_a_request(self) -> None:
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError must never surface to the user.
        with scripted_network([]) as network:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (message or "")
        assert "latin-1" not in (message or "")
        assert network.requests_log == []
