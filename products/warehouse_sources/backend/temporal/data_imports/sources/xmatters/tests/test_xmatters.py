from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xmatters import (
    XmattersSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.source import XmattersSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import (
    PAGE_SIZE,
    XmattersResumeConfig,
    _base_url,
    _format_incremental_value,
    is_valid_subdomain,
    validate_credentials,
)


def _response(items: list[dict[str, Any]], next_url: Optional[str] = None) -> ScriptedResponse:
    body: dict[str, Any] = {"count": len(items), "total": len(items), "data": items}
    if next_url is not None:
        body["links"] = {"next": next_url}
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(XmattersSource(), XmattersSourceConfig(subdomain="acme", username="svc", password="secret"))


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestSubdomainValidation:
    # An editor-controlled subdomain like `attacker.example/` would make the worker send its
    # requests (and Basic auth header) to an arbitrary host instead of *.xmatters.com (SSRF).
    @pytest.mark.parametrize(
        "subdomain",
        [
            "attacker.example/",
            "user@evil.example",
            "acme.evil.example",
            "127.0.0.1:8443/",
            "acme/path",
            "acme?x=",
            "acme#frag",
            "",
            "-acme",
            "acme-",
            "a" * 64,
        ],
    )
    def test_hostile_subdomains_rejected(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is False
        with pytest.raises(ValueError):
            _base_url(subdomain)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            ok, status, _error = validate_credentials("acme", "svc", "secret")
        assert ok is expected_ok
        assert status == expected_status

    @pytest.mark.parametrize(
        "endpoint,expected_path",
        [
            (None, "/api/xm/1/people"),
            ("incidents", "/api/xm/1/incidents"),
            # A per-parent path has an unbound placeholder, so the probe goes to the parent listing.
            ("audits", "/api/xm/1/events"),
            ("group_members", "/api/xm/1/groups"),
            ("group_shifts", "/api/xm/1/groups"),
        ],
    )
    def test_probe_path(self, endpoint: Optional[str], expected_path: str) -> None:
        with scripted_network(always(ScriptedResponse(json={"data": []}))) as network:
            ok, _status, _error = validate_credentials("acme", "svc", "secret", endpoint)
        assert ok is True
        assert [request.path for request in network.requests_log] == [expected_path]


class TestPagination:
    def test_advances_offset_and_sets_page_params(self) -> None:
        result = _driver().run(
            "events",
            [_response([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"), _response([{"id": "2"}])],
        )

        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.requests[0].param("limit") == str(PAGE_SIZE)

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "events", [_response([{"id": "x"}])], resume_state=XmattersResumeConfig(offset=PAGE_SIZE)
        )

        assert result.requests[0].param("offset") == str(PAGE_SIZE)

    def test_empty_page_stops_with_one_request_and_no_checkpoint(self) -> None:
        result = _driver().run("events", [_response([], next_url="/api/xm/1/events?offset=1000")])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_events_incremental_sends_from_and_sort(self) -> None:
        result = _driver().run(
            "events",
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        request = result.requests[0]
        assert request.param("from") == "2026-01-01T00:00:00+00:00"
        assert request.param("sortBy") == "START_TIME"
        assert request.param("sortOrder") == "ASCENDING"


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint,parent_path,child_path,parent_params,child_params,child_rows,expected_rows",
        [
            (
                "audits",
                "/events",
                "/audits",
                {"sortBy": "START_TIME", "sortOrder": "ASCENDING"},
                {
                    "auditType": "EVENT_ANNOTATED,EVENT_CREATED,EVENT_SUSPENDED,EVENT_RESUMED,"
                    "EVENT_COMPLETED,EVENT_TERMINATED,RESPONSE_RECEIVED",
                    "sortOrder": "ASCENDING",
                },
                [{"id": "a-1", "type": "EVENT_CREATED", "at": "2026-02-01T10:00:00.000Z"}],
                [{"id": "a-1", "event_id": "p-1"}],
            ),
            (
                "group_members",
                "/groups",
                "/groups/p-1/members",
                {},
                {},
                [{"group": {"id": "p-1"}, "member": {"id": "m-1", "recipientType": "PERSON"}}],
                [{"group_id": "p-1", "member_id": "m-1"}],
            ),
            (
                "group_shifts",
                "/groups",
                "/groups/p-1/shifts",
                {"groupType": "ON_CALL"},
                {"embed": "rotation"},
                [{"id": "s-1", "name": "Weekdays", "created": "2026-02-01T10:00:00.000Z"}],
                [{"id": "s-1", "group_id": "p-1"}],
            ),
        ],
    )
    def test_fans_out_over_parent_rows(
        self,
        endpoint: str,
        parent_path: str,
        child_path: str,
        parent_params: dict[str, str],
        child_params: dict[str, str],
        child_rows: list[dict[str, Any]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        script = route({child_path: [_response(child_rows)], parent_path: [_response([{"id": "p-1"}])]})
        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert [{key: row[key] for key in expected.keys()} for row, expected in zip(result.rows, expected_rows)] == (
            expected_rows
        )
        assert len(result.rows) == len(expected_rows)
        parent_request, child_request = result.requests
        assert parent_request.path == f"/api/xm/1{parent_path}"
        assert child_request.path == f"/api/xm/1{child_path}"
        for name, value in parent_params.items():
            assert parent_request.param(name) == value
        for name, value in child_params.items():
            assert child_request.param(name) == value
        if endpoint == "audits":
            assert child_request.param("eventId") == "p-1"

    def test_fanout_saves_per_parent_progress(self) -> None:
        script = route(
            {
                "/groups/g-1/members": [_response([{"group": {"id": "g-1"}, "member": {"id": "m-1"}}])],
                "/groups/g-2/members": [_response([{"group": {"id": "g-2"}, "member": {"id": "m-2"}}])],
                "/groups": [_response([{"id": "g-1"}, {"id": "g-2"}])],
            }
        )
        result = _driver().run("group_members", script)

        assert result.raised is None
        assert result.saved_states
        state = result.saved_states[-1].paginator_state
        assert state is not None
        assert "completed" in state

    def test_child_404_for_a_deleted_parent_is_skipped(self) -> None:
        script = route(
            {
                "/groups/gone/members": [ScriptedResponse(status=404, json={"code": 404, "reason": "Not Found"})],
                "/groups/kept/members": [_response([{"group": {"id": "kept"}, "member": {"id": "m-1"}}])],
                "/groups": [_response([{"id": "gone"}, {"id": "kept"}])],
            }
        )
        result = _driver().run("group_members", script)

        assert result.raised is None
        assert [(row["group_id"], row["member_id"]) for row in result.rows] == [("kept", "m-1")]

    def test_child_walks_pages_per_parent(self) -> None:
        script = route(
            {
                "/groups/p-1/shifts": [
                    _response([{"id": "s-1"}], next_url="/api/xm/1/groups/p-1/shifts?offset=1000"),
                    _response([{"id": "s-2"}]),
                ],
                "/groups": [_response([{"id": "p-1"}])],
            }
        )
        result = _driver().run("group_shifts", script)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["s-1", "s-2"]
        assert [r.param("offset") for r in result.requests if r.path.endswith("/shifts")] == ["0", str(PAGE_SIZE)]
