from typing import Any, cast

import pytest

from products.warehouse_sources.sources.beehiiv._config import BeehiivSourceConfig
from products.warehouse_sources.sources.beehiiv.beehiiv import BeehiivResumeConfig, get_resource, validate_credentials
from products.warehouse_sources.sources.beehiiv.settings import ENDPOINTS, MAX_PAGE
from products.warehouse_sources.sources.beehiiv.source import BeehiivSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

TOP_LEVEL_ENDPOINTS = {name: config for name, config in ENDPOINTS.items() if config.fanout is None}
CURSOR_ENDPOINTS = [name for name, config in TOP_LEVEL_ENDPOINTS.items() if config.pagination == "cursor"]
PAGE_ENDPOINTS = [name for name, config in TOP_LEVEL_ENDPOINTS.items() if config.pagination == "page"]


def _pages(style: str, *pages: list[dict[str, Any]]) -> list[ScriptedResponse]:
    responses = []
    for index, rows in enumerate(pages, start=1):
        is_last = index == len(pages)
        if style == "cursor":
            body: dict[str, Any] = {
                "data": rows,
                "has_more": not is_last,
                "next_cursor": None if is_last else f"c{index}",
            }
        else:
            body = {"data": rows, "page": index, "total_pages": len(pages)}
        responses.append(ScriptedResponse(json=body))
    return responses


def _driver(publication_id: str = "pub_123") -> SourceDriver:
    return SourceDriver(BeehiivSource(), BeehiivSourceConfig(api_key="test-key", publication_id=publication_id))


class TestBeehiivResourceConfig:
    def test_publication_id_is_url_quoted_into_the_path(self) -> None:
        # The publication id is user-supplied and lands in the URL path; an unescaped
        # value could reach a different beehiiv endpoint than the one we configured.
        resource = get_resource("Subscriptions", "pub_a b/../webhooks")
        endpoint_config = cast(dict[str, Any], resource["endpoint"])

        assert endpoint_config["path"] == "/publications/pub_a%20b%2F..%2Fwebhooks/subscriptions"


class TestBeehiivCursorPagination:
    @pytest.mark.parametrize("endpoint", CURSOR_ENDPOINTS)
    def test_follows_next_cursor_and_checkpoints_each_non_terminal_page(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], "has_more": True, "next_cursor": "cur-1"}),
                ScriptedResponse(json={"data": [{"id": "b"}], "has_more": True, "next_cursor": "cur-2"}),
                ScriptedResponse(json={"data": [{"id": "c"}], "has_more": False, "next_cursor": None}),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cur-1", "cur-2"]
        assert result.rows == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        assert result.saved_states == [
            BeehiivResumeConfig(paginator_state={"cursor": "cur-1"}),
            BeehiivResumeConfig(paginator_state={"cursor": "cur-2"}),
        ]

    def test_resume_seeds_the_saved_cursor_on_the_first_request(self) -> None:
        result = _driver().run(
            "Subscriptions",
            [ScriptedResponse(json={"data": [{"id": "a"}], "has_more": False, "next_cursor": None})],
            resume_state=BeehiivResumeConfig(paginator_state={"cursor": "cur-saved"}),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cur-saved"]


class TestBeehiivPageNumberPagination:
    @pytest.mark.parametrize("endpoint", PAGE_ENDPOINTS)
    def test_walks_pages_and_stops_at_total_pages(self, endpoint: str) -> None:
        # beehiiv reports total_pages, so the last page must not be followed by a wasted
        # request for an empty page.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], "page": 1, "total_pages": 2}),
                ScriptedResponse(json={"data": [{"id": "b"}], "page": 2, "total_pages": 2}),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert result.saved_states == [BeehiivResumeConfig(paginator_state={"page": 2})]

    def test_stops_at_the_hundred_page_offset_cap(self) -> None:
        # beehiiv rejects offset pagination past page 100, so a publication reporting more
        # pages must stop rather than error the whole sync out.
        result = _driver().run(
            "Posts",
            [
                ScriptedResponse(json={"data": [{"id": str(page)}], "page": page, "total_pages": 500})
                for page in range(1, MAX_PAGE + 1)
            ],
        )

        assert result.raised is None
        assert result.params("page") == [str(page) for page in range(1, MAX_PAGE + 1)]
        assert len(result.rows) == MAX_PAGE

    def test_resume_seeds_the_saved_page(self) -> None:
        result = _driver().run(
            "Posts",
            [ScriptedResponse(json={"data": [{"id": "a"}], "page": 7, "total_pages": 7})],
            resume_state=BeehiivResumeConfig(paginator_state={"page": 7}),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]


class TestBeehiivFanout:
    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "child_segment", "parent_key", "expected_child_params"),
        [
            (
                "PodcastEpisodes",
                "/podcasts",
                "episodes",
                "podcast_id",
                {"order_by": "created", "direction": "asc"},
            ),
            (
                "PollResponses",
                "/polls",
                "responses",
                "poll_id",
                {"order_by": "created", "direction": "asc", "expand[]": "post"},
            ),
            ("SegmentMembers", "/segments", "members", "segment_id", {}),
            ("AutomationJourneys", "/automations", "journeys", "automation_id", {"status": "all"}),
        ],
    )
    def test_walks_every_parent_and_tags_child_rows_with_parent_id(
        self,
        endpoint: str,
        parent_path: str,
        child_segment: str,
        parent_key: str,
        expected_child_params: dict[str, str],
    ) -> None:
        fanout = ENDPOINTS[endpoint].fanout
        assert fanout is not None
        parent_config = ENDPOINTS[fanout.parent_name]
        child_style = ENDPOINTS[endpoint].pagination
        prefix = f"/v2/publications/pub_123{parent_path}"
        result = _driver().run(
            endpoint,
            route(
                {
                    f"{prefix}/a/{child_segment}": _pages(child_style, [{"id": "x1"}], [{"id": "x2"}]),
                    f"{prefix}/b/{child_segment}": _pages(child_style, [{"id": "x1"}]),
                    prefix: _pages(parent_config.pagination, [{"id": "a"}], [{"id": "b"}]),
                }
            ),
        )

        assert result.raised is None
        assert sorted((row[parent_key], row["id"]) for row in result.rows) == [("a", "x1"), ("a", "x2"), ("b", "x1")]
        assert all(f"_{parent_config.name}_id" not in row for row in result.rows)
        child_requests = [request for request in result.requests if request.path.endswith(child_segment)]
        assert len(child_requests) == 3
        for request in child_requests:
            assert request.param("limit") == "100"
            for name, value in expected_child_params.items():
                assert request.param(name) == value
        assert result.saved_states == []

    def test_child_404_for_a_deleted_parent_skips_that_parent(self) -> None:
        prefix = "/v2/publications/pub_123/polls"
        result = _driver().run(
            "PollResponses",
            route(
                {
                    f"{prefix}/gone/responses": [ScriptedResponse(status=404, json={"errors": []})],
                    f"{prefix}/live/responses": _pages("cursor", [{"id": "r1"}]),
                    prefix: _pages("cursor", [{"id": "gone"}, {"id": "live"}]),
                }
            ),
        )

        assert result.raised is None
        assert [(row["poll_id"], row["id"]) for row in result.rows] == [("live", "r1")]


class TestBeehiivValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "allow_missing_scope", "expected_ok"),
        [
            # A beehiiv key scoped to subscriptions only cannot read the publication object;
            # that must not block source creation, but it must fail a per-table check.
            (403, True, True),
            (403, False, False),
            (404, True, False),
        ],
    )
    def test_status_code_maps_to_credential_result(
        self, status_code: int, allow_missing_scope: bool, expected_ok: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=allow_missing_scope,
            )

        assert is_valid is expected_ok
        assert (error is None) is expected_ok
        assert {request.path for request in network.requests_log} == {"/v2/publications/pub_1"}

    def test_transport_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(ConnectionResetError("connection reset"))) as network:
            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert is_valid is False
        assert error is not None and "connection reset" in error
        assert {request.path for request in network.requests_log} == {"/v2/publications/pub_1"}

    def test_api_key_is_registered_for_redaction(self) -> None:
        # The key rides an Authorization header on a tracked session; without redaction it
        # can land in captured request samples.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(
                api_key="super-secret",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert network.session_options[0]["redact_values"] == ("super-secret",)
