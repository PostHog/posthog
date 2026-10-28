from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mem0 import Mem0SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0 import mem0 as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0 import (
    _MATCH_ALL_FILTER,
    Mem0ResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_BASE_URL,
    MEMORIES_ENDPOINT,
    MEMORY_HISTORY_ENDPOINT,
    PROJECTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.source import Mem0Source


def _driver(org_id: str | None = None, project_id: str | None = None) -> SourceDriver:
    return SourceDriver(Mem0Source(), Mem0SourceConfig(api_key="m0-test", org_id=org_id, project_id=project_id))


def _response(
    results: list[dict[str, Any]] | None = None, *, status: int = 200, next_url: str | None = None
) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"count": len(results or []), "next": next_url, "previous": None, "results": results or []},
    )


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_maps_status_code_to_validity(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("m0-test") is expected

        assert network.requests_log[0].path == "/v1/ping/"
        assert network.requests_log[0].headers["authorization"] == "Token m0-test"


class TestMemoriesRows:
    def test_incremental_sync_filters_on_the_users_chosen_field(self) -> None:
        result = _driver().run(
            MEMORIES_ENDPOINT,
            [_response()],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 1, 12, 30, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert result.raised is None
        assert result.requests[0].json() == {
            "filters": {"AND": [_MATCH_ALL_FILTER, {"created_at": {"gte": "2026-07-01"}}]}
        }

    def test_resumes_from_saved_next_url_and_pins_the_original_cutoff(self) -> None:
        # The saved cutoff (not a freshly computed one) must drive the filter on resume, otherwise
        # the resumed run paginates a different server-side result set than the pages it already saw.
        saved_url = f"{MEM0_BASE_URL}/v3/memories/?page=3&page_size=100"
        result = _driver().run(
            MEMORIES_ENDPOINT,
            [_response()],
            resume_state=Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, next_url=saved_url, cutoff="2026-06-01"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("page") == "3"
        assert result.requests[0].json() == {
            "filters": {"AND": [_MATCH_ALL_FILTER, {"updated_at": {"gte": "2026-06-01"}}]}
        }

    def test_ignores_resume_state_saved_by_a_different_endpoint(self) -> None:
        result = _driver().run(
            MEMORIES_ENDPOINT,
            [_response()],
            resume_state=Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=f"{MEM0_BASE_URL}/v1/events/?page=9"),
        )

        assert result.raised is None
        assert result.requests[0].param("page") == "1"


class TestMemoriesRejectedPage:
    def test_a_rejected_next_page_ends_the_table_with_the_rows_already_read(self) -> None:
        # Mem0 keeps putting a `next` link in the memories envelope past the page it answers with
        # 400, so following it failed the whole sync and the table never landed.
        next_url = f"{MEM0_BASE_URL}/v3/memories/?page=2&page_size=100"
        result = _driver().run(
            MEMORIES_ENDPOINT,
            [_response([{"id": "m1"}], next_url=next_url), _response(status=400)],
        )

        assert result.raised is None
        assert result.rows == [{"id": "m1"}]
        assert result.params("page") == ["1", "2"]

    def test_a_resumed_run_ends_the_table_when_its_saved_page_is_rejected(self) -> None:
        # A resumed run's first request is Mem0's own saved `next` link, so a 400 there is the same
        # refusal to page deeper rather than a bad request of ours.
        saved_url = f"{MEM0_BASE_URL}/v3/memories/?page=21&page_size=100"
        result = _driver().run(
            MEMORIES_ENDPOINT,
            [_response(status=400)],
            resume_state=Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, next_url=saved_url),
        )

        assert result.raised is None
        assert result.rows == []
        assert result.params("page") == ["21"]

    @parameterized.expand(
        [
            # A 400 on the first request is a request-validation failure (Mem0 documents an empty
            # `filters` as the cause), not a page Mem0 sent us to — syncing an empty table would hide it.
            ("bad_request_on_first_page", 400, True),
            ("unauthorized_on_a_later_page", 401, False),
            ("not_found_on_a_later_page", 404, False),
        ]
    )
    def test_other_rejections_still_fail_the_sync(self, _name: str, status: int, on_first_request: bool) -> None:
        next_url = f"{MEM0_BASE_URL}/v3/memories/?page=2&page_size=100"
        responses = (
            [_response(status=status)]
            if on_first_request
            else [_response([{"id": "m1"}], next_url=next_url), _response(status=status)]
        )

        result = _driver().run(MEMORIES_ENDPOINT, responses)

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == (1 if on_first_request else 2)


class TestCutoffFormatting:
    @parameterized.expand(
        [
            (datetime(2026, 7, 1, 23, 59, tzinfo=UTC), "2026-07-01"),
            (datetime(2026, 7, 1, 12, 0), "2026-07-01"),  # naive treated as UTC
            (date(2026, 7, 1), "2026-07-01"),
            ("2026-07-01", "2026-07-01"),
            (None, None),
        ]
    )
    def test_formats_cursor_as_date_string(self, value: Any, expected: str | None) -> None:
        assert api_client._format_cutoff(value) == expected


class TestEntitiesRows:
    def test_yields_the_bare_array_response(self) -> None:
        result = _driver().run(ENTITIES_ENDPOINT, [ScriptedResponse(json=[{"id": "alex", "type": "user"}])])

        assert result.raised is None
        assert result.rows == [{"id": "alex", "type": "user"}]
        assert result.requests[0].method == "GET"
        assert result.requests[0].path == "/v1/entities/"

    def test_tolerates_an_enveloped_response(self) -> None:
        result = _driver().run(ENTITIES_ENDPOINT, [ScriptedResponse(json={"results": [{"id": "alex"}]})])

        assert result.raised is None
        assert result.rows == [{"id": "alex"}]

    @parameterized.expand(
        [
            ("org_only", "org_1", None, {"org_id": ("org_1",)}),
            ("project_only", None, "proj_1", {"project_id": ("proj_1",)}),
            ("both", "org_1", "proj_1", {"org_id": ("org_1",), "project_id": ("proj_1",)}),
        ]
    )
    def test_scopes_listing_with_org_and_project_params(
        self, _name: str, org_id: str | None, project_id: str | None, expected_query: dict[str, tuple[str, ...]]
    ) -> None:
        result = _driver(org_id, project_id).run(ENTITIES_ENDPOINT, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.queries[0] == expected_query


class TestMemoryHistoryRows:
    @parameterized.expand(
        [
            ("full_refresh", False, None, _MATCH_ALL_FILTER),
            # The child takes no filters, so the watermark bounds the memories listing on
            # `updated_at`, whichever history field the user picked as the cursor.
            (
                "incremental",
                True,
                datetime(2026, 7, 1, 12, 30, tzinfo=UTC),
                {"AND": [_MATCH_ALL_FILTER, {"updated_at": {"gte": "2026-07-01"}}]},
            ),
        ]
    )
    def test_fans_out_over_every_memories_page(
        self, _name: str, incremental: bool, last_value: datetime | None, expected_filters: dict[str, Any]
    ) -> None:
        next_url = f"{MEM0_BASE_URL}/v3/memories/?page=2&page_size=100"
        result = _driver().run(
            MEMORY_HISTORY_ENDPOINT,
            [
                _response([{"id": "m1"}, {"id": "m2"}], next_url=next_url),
                ScriptedResponse(json=[{"id": "h1", "memory_id": "m1", "event": "ADD"}]),
                # A memory deleted between the listing and its history fetch.
                ScriptedResponse(status=404, json={"detail": "Not found"}),
                _response([{"id": "m3"}], next_url=None),
                ScriptedResponse(json=[{"id": "h3", "memory_id": "m3", "event": "UPDATE"}]),
            ],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
            incremental_field="created_at",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["h1", "h3"]
        assert result.requests[0].json() == {"filters": expected_filters}
        assert result.paths[1:] == [
            "/v1/memories/m1/history/",
            "/v1/memories/m2/history/",
            "/v3/memories/",
            "/v1/memories/m3/history/",
        ]


class TestProjectsRows:
    def test_fans_out_over_organizations_and_tags_rows_with_the_org_id(self) -> None:
        result = _driver().run(
            PROJECTS_ENDPOINT,
            [
                ScriptedResponse(json=[{"org_id": "org_1", "name": "One"}, {"org_id": "org_2", "name": "Two"}]),
                ScriptedResponse(json=[{"project_id": "proj_a", "name": "A"}]),
                ScriptedResponse(json=[{"project_id": "proj_b", "name": "B"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"project_id": "proj_a", "name": "A", "org_id": "org_1"},
            {"project_id": "proj_b", "name": "B", "org_id": "org_2"},
        ]
        assert result.paths == [
            "/api/v1/orgs/organizations/",
            "/api/v1/orgs/organizations/org_1/projects/",
            "/api/v1/orgs/organizations/org_2/projects/",
        ]


class TestEventsRows:
    def test_follows_next_urls_and_checkpoints_after_each_yield(self) -> None:
        next_url = f"{MEM0_BASE_URL}/v1/events/?page=2"
        result = _driver().run(
            EVENTS_ENDPOINT,
            [_response([{"id": "e1"}], next_url=next_url), _response([{"id": "e2"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "e1"}, {"id": "e2"}]
        assert result.requests[1].url == next_url
        assert result.saved_states == [Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=next_url)]

    @parameterized.expand(
        [
            ("absolute", "https://evil.example.com/v1/events/?page=2"),
            ("scheme_relative", "//evil.example.com/v1/events/?page=2"),
            ("non_https", "http://api.mem0.ai/v1/events/?page=2"),
            ("lookalike_host", "https://api.mem0.ai.evil.example.com/v1/events/?page=2"),
        ]
    )
    def test_refuses_to_follow_off_origin_next_links(self, _name: str, next_url: str) -> None:
        # The session carries the API key; a tampered `next` link must never receive a credentialed
        # request or be persisted as resume state.
        result = _driver().run(EVENTS_ENDPOINT, [_response([{"id": "e1"}], next_url=next_url)])

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v1/events/"]
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("absolute", "https://evil.example.com/v1/events/?page=5"),
            ("non_https", "http://api.mem0.ai/v1/events/?page=5"),
        ]
    )
    def test_refuses_to_resume_from_an_off_origin_saved_url(self, _name: str, saved_url: str) -> None:
        result = _driver().run(
            EVENTS_ENDPOINT,
            [],
            resume_state=Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=saved_url),
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestFetchRetry:
    def test_auth_errors_raise_immediately_without_retry(self) -> None:
        result = _driver().run(MEMORIES_ENDPOINT, [_response(status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v3/memories/"]
