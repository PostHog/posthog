from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk import (
    FreshdeskResumeConfig,
    _format_updated_since,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source import FreshdeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshdesk import (
    FreshdeskSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FreshdeskSource(), FreshdeskSourceConfig(subdomain="acme", api_key="key"))


class TestFormatUpdatedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("some-cursor", "some-cursor"),
        ],
    )
    def test_format_updated_since(self, value: Any, expected: str) -> None:
        assert _format_updated_since(value) == expected


class TestRequestParams:
    def test_contacts_incremental_uses_underscore_param(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json=[{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.requests[0].param("_updated_since") == "2026-03-04T00:00:00Z"


TICKETS_PAGE_2 = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=2"
SURVEYS_PAGE_2 = "https://acme.freshdesk.com/api/v2/customer-satisfaction/surveys?per_page=100&next_token=t2"


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, script, next_url",
        [
            (
                "tickets",
                [
                    ScriptedResponse(json=[{"id": 1}], headers={"Link": f'<{TICKETS_PAGE_2}>; rel="next"'}),
                    ScriptedResponse(json=[{"id": 2}]),
                ],
                TICKETS_PAGE_2,
            ),
            (
                "csat_surveys",
                [
                    ScriptedResponse(json={"data": [{"id": 1}], "paging": {"next": SURVEYS_PAGE_2, "previous": None}}),
                    ScriptedResponse(json={"data": [{"id": 2}], "paging": {"next": None, "previous": SURVEYS_PAGE_2}}),
                ],
                SURVEYS_PAGE_2,
            ),
        ],
    )
    def test_paginates_to_the_last_page_and_saves_state(
        self, endpoint: str, script: list[ScriptedResponse], next_url: str
    ) -> None:
        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        assert result.urls[1] == next_url
        # State saved once, after the first (only non-terminal) page.
        assert result.saved_states == [FreshdeskResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=5"
        result = _driver().run(
            "tickets",
            [ScriptedResponse(json=[{"id": 50}])],
            resume_state=FreshdeskResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [50]
        # First request must target the resumed URL, not a freshly-built initial URL.
        assert result.paths[0] == "/api/v2/tickets"
        assert result.requests[0].param("page") == "5"

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run("tickets", [ScriptedResponse(status=status_code, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/api/v2/tickets"]


class TestValidateCredentials:
    def test_connection_error_returns_none(self) -> None:
        with scripted_network(always(requests.ConnectionError("nope"))) as network:
            assert validate_credentials("acme", "key") is None

        assert {request.path for request in network.requests_log} == {"/api/v2/tickets"}


class TestFanout:
    def test_conversations_incremental_windows_the_parent_walk(self) -> None:
        # The child endpoint takes no timestamp filter, so the watermark has to reach the
        # tickets request instead -- otherwise every sync re-walks every ticket.
        result = _driver().run(
            "conversations",
            [ScriptedResponse(json=[{"id": 10}]), ScriptedResponse(json=[{"id": 100}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_since") == "2026-03-04T00:00:00Z"
        assert result.requests[0].param("order_type") == "asc"
        # The child request carries no watermark param of its own.
        assert result.requests[1].param("updated_since") is None

    def test_canned_responses_fan_out_from_folders(self) -> None:
        result = _driver().run(
            "canned_responses",
            [ScriptedResponse(json=[{"id": 1}]), ScriptedResponse(json=[{"id": 5, "folder_id": 1}])],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [5]
        assert result.paths[1] == "/api/v2/canned_response_folders/1/responses"

    def test_solution_articles_walk_categories_then_folders(self) -> None:
        result = _driver().run(
            "solution_articles",
            [
                ScriptedResponse(json=[{"id": 3}]),
                ScriptedResponse(json=[{"id": 4}]),
                ScriptedResponse(json=[{"id": 1, "folder_id": 4, "category_id": 3}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.paths == [
            "/api/v2/solutions/categories",
            "/api/v2/solutions/categories/3/folders",
            "/api/v2/solutions/folders/4/articles",
        ]

    @pytest.mark.parametrize(
        "endpoint, script, expected_paths, parent_key, parent_value",
        [
            (
                "custom_object_records",
                [
                    ScriptedResponse(json={"schemas": [{"id": 30}]}),
                    ScriptedResponse(
                        json={
                            "records": [{"display_id": "BKG-1"}],
                            "_links": {"next": {"href": "/schemas/30/records?page_size=100&next_token=t2"}},
                        }
                    ),
                    ScriptedResponse(
                        json={
                            "records": [{"display_id": "BKG-2"}],
                            "_links": {"next": {"href": "/schemas/30/records?page_size=100&prev_token=t2&next_token="}},
                        }
                    ),
                ],
                ["/api/v2/custom_objects/schemas"] + ["/api/v2/custom_objects/schemas/30/records"] * 2,
                "schema_id",
                30,
            ),
            (
                "custom_object_records",
                [
                    ScriptedResponse(json={"schemas": [{"id": 30}]}),
                    ScriptedResponse(
                        json={
                            "records": [{"display_id": "BKG-1"}],
                            "_links": {"next": {"href": "/schemas/30/records?page_size=100&next_token=t2"}},
                        }
                    ),
                    ScriptedResponse(json={"records": [{"display_id": "BKG-2"}], "_links": {}}),
                ],
                ["/api/v2/custom_objects/schemas"] + ["/api/v2/custom_objects/schemas/30/records"] * 2,
                "schema_id",
                30,
            ),
            (
                "csat_survey_responses",
                [
                    ScriptedResponse(json={"data": [{"id": "s-1"}], "paging": {"next": None}}),
                    ScriptedResponse(
                        json={
                            "data": [{"id": "r-1"}],
                            "paging": {
                                "next": "https://acme.freshdesk.com/api/v2/customer-satisfaction/surveys/s-1/responses?per_page=100&next_token=t2"
                            },
                        }
                    ),
                    ScriptedResponse(json={"data": [{"id": "r-2", "survey_id": "s-1"}], "paging": {"next": None}}),
                ],
                ["/api/v2/customer-satisfaction/surveys"] + ["/api/v2/customer-satisfaction/surveys/s-1/responses"] * 2,
                "survey_id",
                "s-1",
            ),
        ],
    )
    def test_fan_out_pages_the_child_through_its_body_link(
        self,
        endpoint: str,
        script: list[ScriptedResponse],
        expected_paths: list[str],
        parent_key: str,
        parent_value: Any,
    ) -> None:
        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.requests[2].param("next_token") == "t2"
        assert len(result.rows) == 2
        # The parent id is part of the child's primary key, so every row must carry it.
        assert {row[parent_key] for row in result.rows} == {parent_value}
