from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wufoo import WufooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import FORMS_PAGE_LIMIT
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source import WufooSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo import (
    PAGE_SIZE,
    WufooResumeConfig,
    validate_credentials,
)


def _response(count: int, *, data_key: str = "Forms", status: int = 200, drop_key: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_key:
        body[data_key] = [{"Hash": f"h{i}"} for i in range(count)]
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(WufooSource(), WufooSourceConfig(subdomain="acme", api_key="wufoo-key"))


class TestPagination:
    def test_follows_offset_until_short_page(self) -> None:
        result = _driver().run("forms", [_response(PAGE_SIZE), _response(PAGE_SIZE), _response(3)])

        assert len(result.rows) == 2 * PAGE_SIZE + 3
        # pageStart advances by PAGE_SIZE per page; pageSize is pinned on every request.
        assert result.params("pageStart") == ["0", str(PAGE_SIZE), str(2 * PAGE_SIZE)]
        assert all(size == str(PAGE_SIZE) for size in result.params("pageSize"))
        # State is checkpointed after each full page (points at the next offset), never for the short one.
        assert [s.page_start for s in result.saved_states] == [PAGE_SIZE, 2 * PAGE_SIZE]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("forms", [_response(2)], resume_state=WufooResumeConfig(page_start=PAGE_SIZE))

        # Offset 0 is never fetched on resume — the first request targets the saved offset.
        assert result.requests[0].param("pageStart") == str(PAGE_SIZE)
        assert len(result.rows) == 2

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("forms", [_response(0, drop_key=True)])

        # A 200 body without the expected list key means the shape changed — fail loud, not 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryClassification:
    @parameterized.expand([("server_error", 500), ("bad_gateway", 503), ("rate_limited", 429)])
    def test_transient_statuses_are_retried(self, _name: str, status: int) -> None:
        result = _driver().run("forms", [_response(0, status=status), _response(1)])

        # The transient status is retried and the sync completes on the follow-up 200.
        assert len(result.requests) == 2
        assert len(result.rows) == 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_loud(self, _name: str, status: int) -> None:
        result = _driver().run("forms", [_response(0, status=status)])

        # 4xx (other than 429) is a permanent error: it is not retried and surfaces as an HTTPError.
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    def test_invalid_subdomain_short_circuits_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("wufoo-key", "bad subdomain!") is None
        assert network.requests_log == []


class TestWufooSourceResponse:
    @parameterized.expand([("forms",), ("reports",), ("users",)])
    def test_uses_hash_primary_key(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["Hash"]


def _rows(data_key: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={data_key: rows})


def _entries(start: int, count: int) -> ScriptedResponse:
    return _rows("Entries", [{"EntryId": str(i), "Field1": f"answer {i}"} for i in range(start, start + count)])


class TestFanout:
    def test_form_entries_walk_every_form_and_tag_rows_with_form_hash(self) -> None:
        result = _driver().run(
            "form_entries",
            route(
                {
                    "/forms.json": [_rows("Forms", [{"Hash": "forma"}, {"Hash": "formb"}])],
                    "/forms/forma/entries.json": [_entries(1, PAGE_SIZE), _entries(PAGE_SIZE + 1, 2)],
                    "/forms/formb/entries.json": [_entries(1, 0)],
                }
            ),
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 2
        assert {row["form_hash"] for row in result.rows} == {"forma"}
        assert all("Hash" not in row and "_forms_Hash" not in row for row in result.rows)

        parent, *children = result.requests
        assert (parent.param("page"), parent.param("limit"), parent.param("pageStart")) == (
            "1",
            str(FORMS_PAGE_LIMIT),
            None,
        )
        assert [(r.path.rsplit("/", 2)[-2], r.param("pageStart")) for r in children] == [
            ("forma", "0"),
            ("forma", str(PAGE_SIZE)),
            ("formb", "0"),
        ]
        assert all(
            (r.param("pageSize"), r.param("sort"), r.param("sortDirection"), r.param("system"))
            == (str(PAGE_SIZE), "EntryId", "ASC", "true")
            for r in children
        )

    @parameterized.expand(
        [
            # Fields endpoints are single responses, so a full-looking page is not followed.
            (
                "form_fields_single_page",
                "form_fields",
                "/forms.json",
                "Forms",
                "/forms/p1/fields.json",
                "Fields",
                PAGE_SIZE,
                1,
            ),
            (
                "report_fields_single_page",
                "report_fields",
                "/reports.json",
                "Reports",
                "/reports/p1/fields.json",
                "Fields",
                PAGE_SIZE,
                1,
            ),
            # A report that ignores pageSize and sends every entry must not be asked for the same rows again.
            (
                "report_entries_unpaged_response",
                "report_entries",
                "/reports.json",
                "Reports",
                "/reports/p1/entries.json",
                "Entries",
                PAGE_SIZE + 50,
                1,
            ),
            (
                "report_entries_short_page",
                "report_entries",
                "/reports.json",
                "Reports",
                "/reports/p1/entries.json",
                "Entries",
                3,
                1,
            ),
        ]
    )
    def test_child_stops_after_its_last_page(
        self,
        _name: str,
        endpoint: str,
        parent_path: str,
        parent_key: str,
        child_path: str,
        child_key: str,
        child_rows: int,
        expected_child_requests: int,
    ) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    parent_path: [_rows(parent_key, [{"Hash": "p1"}])],
                    child_path: [_rows(child_key, [{"EntryId": str(i), "ID": f"Field{i}"} for i in range(child_rows)])],
                }
            ),
        )

        assert result.raised is None
        assert len(result.rows) == child_rows
        assert result.paths.count(f"/api/v3{child_path}") == expected_child_requests
        # Neither parent list takes the offset params the top-level tables send.
        assert result.requests[0].param("pageStart") is None

    def test_report_entries_stop_when_an_unpaged_response_repeats_a_full_page(self) -> None:
        def respond(request: Any) -> ScriptedResponse:
            if request.path.endswith("/reports.json"):
                return _rows("Reports", [{"Hash": "p1"}])
            return _entries(1, PAGE_SIZE)

        result = _driver().run("report_entries", respond)

        assert result.raised is None
        assert result.paths.count("/api/v3/reports/p1/entries.json") == 2
        assert len(result.rows) == PAGE_SIZE

    def test_forms_parent_requests_next_page_only_after_a_full_page(self) -> None:
        def respond(request: Any) -> ScriptedResponse:
            if request.path.endswith("/forms.json"):
                count = FORMS_PAGE_LIMIT if request.param("page") == "1" else 1
                offset = 0 if request.param("page") == "1" else FORMS_PAGE_LIMIT
                return _rows("Forms", [{"Hash": f"f{offset + i}"} for i in range(count)])
            return _rows("Fields", [{"ID": "Field1"}])

        result = _driver().run("form_fields", respond)

        assert result.raised is None
        assert result.params("page")[0] == "1"
        assert [p for p in result.params("page") if p is not None] == ["1", "2"]
        assert len(result.rows) == FORMS_PAGE_LIMIT + 1
        assert len({row["form_hash"] for row in result.rows}) == FORMS_PAGE_LIMIT + 1

    def test_resumes_fanout_from_saved_parent_and_offset(self) -> None:
        resume = WufooResumeConfig(
            fanout_state={
                "completed": ["forms/forma/entries.json"],
                "current": "forms/formb/entries.json",
                "child_state": {"offset": PAGE_SIZE},
            }
        )
        result = _driver().run(
            "form_entries",
            route(
                {
                    "/forms.json": [_rows("Forms", [{"Hash": "forma"}, {"Hash": "formb"}])],
                    "/forms/formb/entries.json": [_entries(PAGE_SIZE + 1, 2)],
                }
            ),
            resume_state=resume,
        )

        assert result.raised is None
        assert "/api/v3/forms/forma/entries.json" not in result.paths
        assert result.requests[-1].param("pageStart") == str(PAGE_SIZE)
        assert [row["EntryId"] for row in result.rows] == [str(PAGE_SIZE + 1), str(PAGE_SIZE + 2)]
        assert result.final_state is not None
        assert result.final_state.fanout_state["completed"] == [
            "forms/forma/entries.json",
            "forms/formb/entries.json",
        ]

    def test_child_error_fails_the_sync(self) -> None:
        result = _driver().run(
            "report_entries",
            route(
                {
                    "/reports.json": [_rows("Reports", [{"Hash": "r1"}])],
                    "/reports/r1/entries.json": [ScriptedResponse(status=401, json={})],
                }
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)
