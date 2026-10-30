from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import Request
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub import (
    NO_PARTNER_PROGRAM_MESSAGE,
    DubCursorPaginator,
    DubLinksScopePaginator,
    DubResumeConfig,
    _scrub_link_password,
    check_endpoint_access,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import (
    DUB_ENDPOINTS,
    ENDPOINTS,
    PARTNER_PROGRAM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.source import DubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dub import DubSourceConfig


def _rows(n: int, prefix: str = "row") -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}", "createdAt": "2026-01-01T00:00:00.000Z"} for i in range(n)]


def _params(resource: EndpointResource) -> dict[str, Any]:
    endpoint = resource["endpoint"]
    assert isinstance(endpoint, dict)
    params = endpoint.get("params")
    assert params is not None
    return params


class TestDubCursorPaginator:
    def test_fresh_paginator_does_not_inject_cursor_on_first_request(self) -> None:
        paginator = DubCursorPaginator(page_size=100)
        request = Request(method="GET", url="https://api.dub.co/links", params={})
        paginator.init_request(request)

        assert "startingAfter" not in request.params

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = DubCursorPaginator(page_size=3)
        paginator.update_state(MagicMock(), data=_rows(1))

        assert paginator.get_resume_state() is None


class TestDubLinksScopePaginator:
    def test_walk_ends_once_the_last_folder_is_exhausted(self) -> None:
        paginator = DubLinksScopePaginator(page_size=3, folder_ids=["fold_a"])
        paginator.update_state(MagicMock(), data=_rows(1))
        paginator.update_state(MagicMock(), data=_rows(1))

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_resume_state_round_trip_keeps_the_scope(self) -> None:
        paginator = DubLinksScopePaginator(page_size=3, folder_ids=["fold_a", "fold_b"])
        paginator.update_state(MagicMock(), data=_rows(1))
        paginator.update_state(MagicMock(), data=_rows(3))

        state = paginator.get_resume_state()
        assert state == {"scope_index": 1, "starting_after": "row-2"}

        resumed = DubLinksScopePaginator(page_size=3, folder_ids=["fold_a", "fold_b"])
        resumed.set_resume_state(state or {})
        request = Request(method="GET", url="https://api.dub.co/links", params={})
        resumed.init_request(request)

        assert request.params["folderId"] == "fold_a"
        assert request.params["startingAfter"] == "row-2"


class TestGetResource:
    def test_event_endpoint_uses_watermark_as_start(self) -> None:
        watermark = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
        resource = get_resource("lead_events", True, watermark)
        params = _params(resource)

        assert params["start"] == watermark.isoformat()
        assert "interval" not in params

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_every_endpoint_builds_a_resource(self, endpoint: str) -> None:
        resource = get_resource(endpoint, False, None)

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        params = _params(resource)
        config = DUB_ENDPOINTS[endpoint]
        if config.pagination == "single":
            # The aggregate endpoints reject an unknown page-size param with a 422.
            assert config.page_size_param not in params
        else:
            assert params[config.page_size_param] == config.page_size


class TestScrubLinkPassword:
    def test_leaves_rows_without_passwords_untouched(self) -> None:
        row = {"id": "l1", "url": "https://example.com", "link": {"id": "l2"}}

        assert _scrub_link_password(row) == row


class TestDubSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(DubSource(), DubSourceConfig(api_key="dub_test"))

    def test_cursor_endpoint_saves_cursor_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "customers",
            [
                ScriptedResponse(json=_rows(100, "a")),
                ScriptedResponse(json=_rows(100, "b")),
                ScriptedResponse(json=_rows(1, "c")),
            ],
        )

        assert result.raised is None
        assert result.params("startingAfter") == [None, "a-99", "b-99"]
        assert result.saved_states == [
            DubResumeConfig(starting_after="a-99"),
            DubResumeConfig(starting_after="b-99"),
        ]
        assert len(result.rows) == 201

    def test_links_walk_covers_unfiled_links_then_every_folder(self) -> None:
        # Without the per-folder passes only the first request is made, and every link filed
        # into a folder is missing from the table while the sync still reports success.
        result = self._driver().run(
            "links",
            [
                ScriptedResponse(json=[{"id": "fold_a"}, {"id": "fold_b"}]),
                *(ScriptedResponse(json=_rows(1, prefix)) for prefix in ("unfiled", "a", "b")),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/folders", "/links", "/links", "/links"]
        assert result.params("folderId") == [None, None, "fold_a", "fold_b"]
        assert [row["id"] for row in result.rows] == ["unfiled-0", "a-0", "b-0"]

    def test_cursor_endpoint_resumes_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "customers",
            [ScriptedResponse(json=_rows(1))],
            resume_state=DubResumeConfig(starting_after="a-42"),
        )

        assert result.raised is None
        assert result.params("startingAfter") == ["a-42"]

    def test_incremental_event_sync_ignores_saved_page_state(self) -> None:
        # On incremental runs the timestamp watermark is the resume cursor; replaying a
        # saved page number against a fresher `start` filter would skip rows.
        result = self._driver().run(
            "click_events",
            [ScriptedResponse(json=_rows(1)), ScriptedResponse(json=[])],
            resume_state=DubResumeConfig(page=7),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00",
        )

        assert result.raised is None
        assert result.saved_states == []
        assert result.params("page")[0] == "1"
        assert result.params("start")[0] == "2026-05-01T00:00:00"

    def test_full_refresh_event_sync_still_uses_page_resume(self) -> None:
        result = self._driver().run(
            "click_events",
            [ScriptedResponse(json=_rows(1)), ScriptedResponse(json=[])],
            resume_state=DubResumeConfig(page=7),
        )

        assert result.raised is None
        assert result.params("page")[0] == "7"


class TestPartnerAnalyticsWalk:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(DubSource(), DubSourceConfig(api_key="dub_test"))

    def test_walk_resumes_at_the_partner_after_the_last_written_one(self) -> None:
        result = self._driver().run(
            "partner_analytics_timeseries",
            [
                ScriptedResponse(json=[{"id": "pn_a"}, {"id": "pn_b"}]),
                ScriptedResponse(json=[{"start": "2026-01-01", "clicks": 2}]),
            ],
            resume_state=DubResumeConfig(scope_index=1),
        )

        assert result.raised is None
        assert result.paths == ["/partners", "/partners/analytics"]
        assert result.params("partnerId") == [None, "pn_b"]
        assert result.saved_states == [DubResumeConfig(scope_index=2)]
        assert result.rows == [{"start": "2026-01-01", "clicks": 2, "partnerId": "pn_b"}]

    def test_workspace_without_a_partner_program_yields_no_rows(self) -> None:
        # /partners answers 404 without a program, which is an empty table rather than a
        # broken sync, so the walk must not raise.
        result = self._driver().run(
            "partner_analytics_timeseries",
            [ScriptedResponse(status=404, json={"error": {"message": "Program not found"}})],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/partners"]


class TestPartnerProgramTablesWithoutAProgram:
    # Dub resolves the workspace's default partner program before reading any of these lists,
    # so a workspace without one gets this 404 on the table's own list endpoint.
    _NOT_FOUND = {"error": {"code": "not_found", "message": "Program not found"}}

    def test_404_elsewhere_still_fails(self) -> None:
        # The tolerance is scoped to the partner-program tables; a 404 anywhere else is a real
        # error and must not be swallowed into an empty table.
        result = SourceDriver(DubSource(), DubSourceConfig(api_key="dub_test")).run(
            "customers", [ScriptedResponse(status=404, json=self._NOT_FOUND)]
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/customers"]


class TestCredentialValidation:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        response = ScriptedResponse(status=status_code, json={"error": {"code": "forbidden", "message": "Nope"}})
        with scripted_network([response]) as network:
            valid, message = validate_credentials("dub_test")

        assert valid is expected_valid
        assert (message is None) is expected_valid
        assert [request.path for request in network.requests_log] == ["/links"]
        assert network.requests_log[0].param("pageSize") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer dub_test"

    def test_personal_key_gets_workspace_guidance_not_raw_dub_error(self) -> None:
        # A personal (non-workspace) key fails with Dub's raw "workspaceId" copy about a missing
        # query param — replace it with guidance to use a workspace key.
        response = ScriptedResponse(
            status=400,
            json={
                "error": {
                    "code": "bad_request",
                    "message": "Workspace ID not found. Did you forget to include a `workspaceId` query parameter?",
                }
            },
        )
        with scripted_network([response]) as network:
            valid, message = validate_credentials("dub_test")

        assert valid is False
        assert message is not None
        assert "workspaceId" not in message
        assert "workspace API key" in message
        assert [request.path for request in network.requests_log] == ["/links"]

    def test_check_endpoint_access_surfaces_api_denial_message(self) -> None:
        response = ScriptedResponse(
            status=403, json={"error": {"code": "forbidden", "message": "Requires a Business plan or higher."}}
        )
        with scripted_network([response]) as network:
            assert check_endpoint_access("dub_test", "click_events") == "Requires a Business plan or higher."

        assert [request.path for request in network.requests_log] == ["/events"]
        assert network.requests_log[0].param("event") == "clicks"
        assert network.requests_log[0].param("interval") == "24h"

    @pytest.mark.parametrize("endpoint", PARTNER_PROGRAM_ENDPOINTS)
    def test_check_endpoint_access_reads_404_on_partner_tables_as_no_program(self, endpoint: str) -> None:
        # Dub answers these with a bare "Program not found", which reads as a broken connector
        # to a user who never had a partner program.
        response = ScriptedResponse(status=404, json={"error": {"code": "not_found", "message": "Program not found"}})
        with scripted_network([response]) as network:
            assert check_endpoint_access("dub_test", endpoint) == NO_PARTNER_PROGRAM_MESSAGE

        assert [request.path for request in network.requests_log] == [DUB_ENDPOINTS[endpoint].path]

    def test_check_endpoint_access_leaves_other_tables_reachable_on_404(self) -> None:
        response = ScriptedResponse(status=404, json={"error": {"code": "not_found", "message": "Program not found"}})
        with scripted_network([response]) as network:
            assert check_endpoint_access("dub_test", "customers") is None

        assert [request.path for request in network.requests_log] == ["/customers"]

    @pytest.mark.parametrize("status_code", [200, 429, 500])
    def test_check_endpoint_access_only_denials_block(self, status_code: int) -> None:
        # A throttle or transient 5xx must never hide a table from the schema picker.
        response = ScriptedResponse(status=status_code, json={"error": {"code": "x", "message": "x"}})
        with scripted_network(always(response)) as network:
            assert check_endpoint_access("dub_test", "payouts") is None

        assert {request.path for request in network.requests_log} == {"/payouts"}
