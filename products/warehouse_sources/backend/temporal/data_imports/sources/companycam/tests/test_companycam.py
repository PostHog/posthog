from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.companycam import (
    CompanycamCursorPaginator,
    CompanycamResumeConfig,
    _to_iso8601,
    _to_unix_timestamp,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source import CompanycamSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.companycam import (
    CompanycamSourceConfig,
)


class TestCompanycamCursorPaginator:
    @pytest.mark.parametrize(
        ("has_next_header", "next_cursor_header", "expected_has_next"),
        [
            ("true", "cursor-1", True),
            ("false", "", False),
            (None, "cursor-2", True),
            (None, "", False),
            ("true", "", False),  # header says more but no cursor to fetch it with
        ],
    )
    def test_update_state(self, has_next_header: str | None, next_cursor_header: str, expected_has_next: bool) -> None:
        paginator = CompanycamCursorPaginator(per_page=100)
        response = MagicMock()
        headers = {"X-Next-Cursor": next_cursor_header}
        if has_next_header is not None:
            headers["X-Has-Next"] = has_next_header
        response.headers = headers

        paginator.update_state(response)

        assert paginator.has_next_page is expected_has_next


class TestConverters:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, "2023-11-14T22:13:20+00:00"),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "2023-11-14T22:13:20+00:00"),
            (None, None),
        ],
    )
    def test_to_iso8601(self, value: Any, expected: str | None) -> None:
        assert _to_iso8601(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, "1700000000"),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "1700000000"),
            (None, None),
        ],
    )
    def test_to_unix_timestamp(self, value: Any, expected: str | None) -> None:
        assert _to_unix_timestamp(value) == expected


class TestGetResource:
    def test_full_refresh_endpoint_never_gets_incremental_param(self) -> None:
        # Users has no incremental_query_param at all, regardless of should_use_incremental_field.
        resource = cast(dict[str, Any], get_resource("Users", should_use_incremental_field=True))
        assert "modified_since" not in resource["endpoint"]["params"]
        assert "start_date" not in resource["endpoint"]["params"]


class TestCompanycamSourceResumeBehavior:
    """End-to-end resume behaviour of ``CompanycamSource`` via ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CompanycamSource(), CompanycamSourceConfig(api_key="test-key"))

    def test_page_number_endpoint_saves_page_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Users",
            [
                ScriptedResponse(json=[{"id": "1"}]),
                ScriptedResponse(json=[{"id": "2"}]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert result.saved_states == [
            CompanycamResumeConfig(page=2),
            CompanycamResumeConfig(page=3),
        ]

    def test_page_number_endpoint_resumes_from_saved_page(self) -> None:
        result = self._driver().run("Users", [ScriptedResponse(json=[])], resume_state=CompanycamResumeConfig(page=5))

        assert result.raised is None
        assert result.params("page") == ["5"]

    def test_cursor_endpoint_saves_cursor_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Photos",
            [
                ScriptedResponse(json=[{"id": "p1"}], headers={"X-Has-Next": "true", "X-Next-Cursor": "cursor-1"}),
                ScriptedResponse(json=[{"id": "p2"}], headers={"X-Has-Next": "false", "X-Next-Cursor": ""}),
            ],
        )

        assert result.raised is None
        assert result.params("after") == [None, "cursor-1"]
        assert result.rows == [{"id": "p1"}, {"id": "p2"}]
        assert result.saved_states == [CompanycamResumeConfig(cursor="cursor-1")]

    def test_cursor_endpoint_resumes_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "Photos",
            [ScriptedResponse(json=[], headers={"X-Has-Next": "false"})],
            resume_state=CompanycamResumeConfig(cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("after") == ["cursor-resumed"]

    def test_single_page_endpoint_never_saves_state(self) -> None:
        result = self._driver().run("ChecklistTemplates", [ScriptedResponse(json=[{"id": "t1"}])])

        assert result.raised is None
        assert result.rows == [{"id": "t1"}]
        assert result.saved_states == []

    def test_incremental_sync_sends_filter_param_once_watermark_exists(self) -> None:
        result = self._driver().run(
            "Projects",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("modified_since") == ["2023-11-14T22:13:20+00:00"]


class TestCompanycamFanout:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CompanycamSource(), CompanycamSourceConfig(api_key="test-key"))

    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "parent_pages", "child_template", "parent_key"),
        [
            (
                "ProjectLabels",
                "/projects",
                [ScriptedResponse(json=[{"id": "a"}]), ScriptedResponse(json=[{"id": "b"}]), ScriptedResponse(json=[])],
                "/projects/{}/labels",
                "project_id",
            ),
            (
                "PhotoTags",
                "/photos",
                [
                    ScriptedResponse(json=[{"id": "a"}], headers={"X-Has-Next": "true", "X-Next-Cursor": "c1"}),
                    ScriptedResponse(json=[{"id": "b"}], headers={"X-Has-Next": "false", "X-Next-Cursor": ""}),
                ],
                "/photos/{}/tags",
                "photo_id",
            ),
        ],
    )
    def test_walks_every_parent_and_tags_child_rows_with_parent_id(
        self,
        endpoint: str,
        parent_path: str,
        parent_pages: list[ScriptedResponse],
        child_template: str,
        parent_key: str,
    ) -> None:
        result = self._driver().run(
            endpoint,
            route(
                {
                    parent_path: parent_pages,
                    child_template.format("a"): [
                        ScriptedResponse(json=[{"id": "t1"}]),
                        ScriptedResponse(json=[{"id": "t2"}]),
                        ScriptedResponse(json=[]),
                    ],
                    child_template.format("b"): [ScriptedResponse(json=[{"id": "t1"}]), ScriptedResponse(json=[])],
                }
            ),
        )

        assert result.raised is None
        assert sorted((row[parent_key], row["id"]) for row in result.rows) == [("a", "t1"), ("a", "t2"), ("b", "t1")]
        child_pages = [
            request.param("page") for request in result.requests if request.path.endswith(child_template.format("a"))
        ]
        assert child_pages == ["1", "2", "3"]
        assert result.saved_states == []


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (401, False), (403, False)])
    def test_validate_credentials(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("test-key", "v2") is expected

        assert [request.path for request in network.requests_log] == ["/v2/company"]
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"
        assert network.session_options[0]["redact_values"] == ("test-key",)
        assert network.session_options[0]["capture"] is False
