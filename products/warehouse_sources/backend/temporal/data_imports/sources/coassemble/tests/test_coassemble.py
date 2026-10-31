from typing import Any, cast

from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble import coassemble
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.coassemble import (
    COASSEMBLE_BASE_URL,
    PAGE_SIZE,
    CoassembleResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import (
    COASSEMBLE_ENDPOINTS,
    ENDPOINTS,
    USAGE_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.source import CoassembleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coassemble import (
    CoassembleSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CoassembleSource(), CoassembleSourceConfig(workspace_id="ws-1", api_key="sk-key"))


def _page(prefix: str, start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}"} for i in range(start, start + count)]


class TestListEndpointPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "courses",
            [ScriptedResponse(json=_page("c", 0, 1))],
            resume_state=CoassembleResumeConfig(next_page=2),
        )

        # Pages 0 and 1 must never be re-fetched on resume.
        assert result.raised is None
        assert result.rows == _page("c", 0, 1)
        assert result.params("page") == ["2"]

    @parameterized.expand([("string", "nope"), ("object_without_list", {"count": 1})])
    def test_non_list_body_fails_loudly(self, _name: str, body: Any) -> None:
        # List endpoints document a plain JSON array; any other 200 body means the response shape
        # changed — fail loud instead of silently syncing 0 rows.
        result = _driver().run("courses", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("courses", [ScriptedResponse(status=status, json={"error": "denied"})])

        assert isinstance(result.raised, requests.HTTPError)


class TestTrackingFanOut:
    def test_iterates_courses_and_injects_course_id(self) -> None:
        result = _driver().run(
            "course_trackings",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 22}]),
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json=[{"id": 3}]),
            ],
        )

        # Tracking rows don't reference their course, so the parent id is stamped in (also part of
        # the primary key — see settings.py).
        assert result.raised is None
        assert result.rows == [
            {"id": 1, "course_id": 11},
            {"id": 2, "course_id": 11},
            {"id": 3, "course_id": 22},
        ]
        assert result.paths == [
            "/api/v1/headless/courses",
            "/api/v1/headless/trackings",
            "/api/v1/headless/trackings",
        ]
        assert {request.origin for request in result.requests} == {"https://api.coassemble.com"}
        assert result.params("id") == [None, "11", "22"]
        # Each course lands in `completed` once its pages are exhausted.
        assert result.saved_states[-1] == CoassembleResumeConfig(
            fanout_state={"completed": ["/trackings?id=11", "/trackings?id=22"], "current": None, "child_state": None}
        )

    def test_resumes_by_skipping_completed_courses(self) -> None:
        result = _driver().run(
            "course_trackings",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 22}]),
                ScriptedResponse(json=[{"id": 9}]),
            ],
            resume_state=CoassembleResumeConfig(
                fanout_state={"completed": ["/trackings?id=11"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 9, "course_id": 22}]
        assert result.paths == ["/api/v1/headless/courses", "/api/v1/headless/trackings"]
        assert result.params("id") == [None, "22"]

    def test_pre_migration_bookmark_resumes_exactly(self) -> None:
        # An old-shape bookmark (completed_course_ids + current_course_id + next_page) is translated
        # into the framework fan-out state: completed courses are skipped and the in-progress course
        # resumes at the saved page.
        result = _driver().run(
            "course_trackings",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 22}]),
                ScriptedResponse(json=[{"id": 9}]),
            ],
            resume_state=CoassembleResumeConfig(next_page=1, completed_course_ids=[11], current_course_id=22),
        )

        assert result.raised is None
        assert result.rows == [{"id": 9, "course_id": 22}]
        assert result.paths == ["/api/v1/headless/courses", "/api/v1/headless/trackings"]
        assert result.params("id") == [None, "22"]
        assert result.params("page") == ["0", "1"]

    def test_page_cap_stops_runaway_course(self) -> None:
        # Every trackings page is full, so without the cap this would page forever.
        with mock.patch.object(coassemble, "MAX_FAN_OUT_PAGES_PER_PARENT", 2):
            result = _driver().run(
                "course_trackings",
                [
                    ScriptedResponse(json=[{"id": 11}]),
                    ScriptedResponse(json=[{"id": i} for i in range(PAGE_SIZE)]),
                    ScriptedResponse(json=[{"id": i} for i in range(PAGE_SIZE)]),
                ],
            )

        assert result.raised is None
        assert len(result.rows) == 2 * PAGE_SIZE
        assert result.params("page") == ["0", "0", "1"]


class TestFanOutEndpointShapes:
    @parameterized.expand(
        [
            (
                "screen_trackings",
                "/courses",
                {"id": 11},
                "/screen/trackings?id=11",
                {"id": 1},
                {"id": 1, "course_id": 11},
            ),
            (
                "collection_trackings",
                "/collections",
                {"id": 7},
                "/collection/trackings?id=7",
                {"id": 1},
                {"id": 1, "collection_id": 7},
            ),
            (
                "client_allowances",
                "/clients",
                {"clientIdentifier": "acme"},
                "/usage/client/acme",
                {"metric": "ir", "limit": 10},
                {"metric": "ir", "limit": 10, "clientIdentifier": "acme"},
            ),
        ]
    )
    def test_walks_parent_and_stamps_parent_reference(
        self,
        endpoint: str,
        parent_path: str,
        parent_row: dict[str, Any],
        child_path: str,
        child_row: dict[str, Any],
        expected_row: dict[str, Any],
    ) -> None:
        # Child rows name no parent, so a wrong resolve field or path template would either 404 or
        # land rows whose primary key is half null.
        result = _driver().run(endpoint, [ScriptedResponse(json=[parent_row]), ScriptedResponse(json=[child_row])])

        assert result.raised is None
        assert result.rows == [expected_row]
        assert result.paths == [
            f"/api/v1/headless{parent_path}",
            f"/api/v1/headless{child_path.partition('?')[0]}",
        ]
        assert {request.origin for request in result.requests} == {"https://api.coassemble.com"}
        if "?" in child_path:
            assert result.requests[1].param("id") == str(parent_row["id"])


class TestClientUsagePagination:
    def test_full_page_advances_until_short_page(self) -> None:
        full = [{"clientIdentifier": f"c-{i}", "metric": "ir"} for i in range(USAGE_PAGE_SIZE)]
        result = _driver().run(
            "client_usage",
            [
                ScriptedResponse(json={"page": 0, "length": USAGE_PAGE_SIZE, "data": full}),
                ScriptedResponse(
                    json={"page": 1, "length": USAGE_PAGE_SIZE, "data": [{"clientIdentifier": "z", "metric": "ir"}]}
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == USAGE_PAGE_SIZE + 1
        assert result.params("page") == ["0", "1"]

    def test_missing_envelope_key_fails_loudly(self) -> None:
        result = _driver().run("client_usage", [ScriptedResponse(json={"page": 0, "length": USAGE_PAGE_SIZE})])

        assert isinstance(result.raised, ValueError)
        assert "Required data_selector" in str(result.raised)


class TestWorkspaceAllowances:
    def test_reads_one_unpaged_request(self) -> None:
        # The endpoint documents no page/length params, so the request must carry none.
        rows = [{"metric": "ir", "limit": 500, "currentUsage": 12}, {"metric": "imageUsage", "limit": None}]
        result = _driver().run("workspace_allowances", [ScriptedResponse(json=rows)])

        assert result.raised is None
        assert result.rows == rows
        assert result.paths == ["/api/v1/headless/usage/allowances"]
        assert result.params("page") == [None]
        assert result.params("length") == [None]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Coassemble workspace ID or API key"),
            ("forbidden", 403, False, "Invalid Coassemble workspace ID or API key"),
            ("server_error", 500, False, "Coassemble returned HTTP 500"),
        ]
    )
    def test_status_maps_to_result(
        self, _name: str, status: int, expected_ok: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("ws-1", "sk-key") == (expected_ok, expected_message)

        assert network.requests_log[0].url == f"{COASSEMBLE_BASE_URL}/courses?page=0&length=1"
        assert network.requests_log[0].headers["authorization"] == "COASSEMBLE:ws-1:sk-key"
        assert network.session_options[0]["redact_values"] == ("sk-key",)

    def test_connection_error_is_inconclusive(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            ok, message = validate_credentials("ws-1", "sk-key")

        assert ok is False
        assert message is not None and "Could not connect to Coassemble" in message
        assert {request.path for request in network.requests_log} == {"/api/v1/headless/courses"}


class TestResumeStateCompatibility:
    def test_pre_migration_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does `dataclass(**saved)` — state saved before the
        # framework migration must still construct.
        assert CoassembleResumeConfig(
            **cast("dict[str, Any]", {"next_page": 3, "completed_course_ids": [11], "current_course_id": 22})
        ) == CoassembleResumeConfig(next_page=3, completed_course_ids=[11], current_course_id=22)


class TestCoassembleSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        first_page: Any = {"data": []} if endpoint == "client_usage" else []
        result = _driver().run(endpoint, [ScriptedResponse(json=first_page)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == COASSEMBLE_ENDPOINTS[endpoint].primary_keys
        # Trackings/courses only guarantee mutable progress timestamps, so we don't partition.
        assert result.response.partition_mode is None

    def test_trackings_key_includes_injected_course_id(self) -> None:
        # Tracking rows are aggregated across every course; without the parent id in the key,
        # per-course id collisions would seed duplicate rows that every later merge multi-matches.
        assert COASSEMBLE_ENDPOINTS["course_trackings"].primary_keys == ["course_id", "id"]

    def test_clients_and_users_use_identifier_keys(self) -> None:
        # Neither object carries a numeric `id` in the API response.
        assert COASSEMBLE_ENDPOINTS["clients"].primary_keys == ["clientIdentifier"]
        assert COASSEMBLE_ENDPOINTS["users"].primary_keys == ["identifier"]
