from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opinionstage import (
    OpinionStageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.opinion_stage import (
    OpinionStageResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.source import OpinionStageSource


def _page(items: list[dict[str, Any]], next_link: str | None) -> ScriptedResponse:
    # JSON:API collection envelope: rows under `data`, pagination via `links.next`.
    return ScriptedResponse(json={"data": items, "meta": {}, "links": {"self": "s", "next": next_link}})


def _counted_page(items: list[dict[str, Any]], current: int, total: int) -> ScriptedResponse:
    # The envelope the OpenAPI spec documents: page counters under `meta.page` and no `links.next`.
    return ScriptedResponse(
        json={"data": items, "meta": {"page": {"current": current, "size": 100, "total": total}}, "links": {}}
    )


class TestOpinionStage:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OpinionStageSource(), OpinionStageSourceConfig(api_key="os-key"))

    def test_resumes_from_saved_page(self) -> None:
        result = self._driver().run(
            "items",
            [_page([{"id": "2"}], next_link="p3"), _page([{"id": "3"}], next_link=None)],
            resume_state=OpinionStageResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2", "3"]
        # Page 1 is never fetched on resume — the first request targets page 2.
        assert result.params("page[number]") == ["2", "3"]

    @parameterized.expand([("responses",), ("questions",)])
    def test_fan_out_walks_every_item_and_every_child_page(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            route(
                {
                    "/api/v2/items": [
                        _counted_page([{"id": "item-a"}, {"id": "item-gone"}], current=1, total=2),
                        _counted_page([{"id": "item-b"}], current=2, total=2),
                    ],
                    f"/api/v2/items/item-a/{endpoint}": [
                        _counted_page([{"id": "1", "attributes": {"title": None}}], current=1, total=2),
                        _page([{"id": "2"}], next_link=None),
                    ],
                    f"/api/v2/items/item-gone/{endpoint}": [
                        ScriptedResponse(
                            status=404, json={"errors": [{"status": "404", "title": "resource not found"}]}
                        )
                    ],
                    f"/api/v2/items/item-b/{endpoint}": [_page([{"id": "1"}], next_link=None)],
                }
            ),
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["item_id", "id"]
        assert [(row["item_id"], row["id"]) for row in result.rows] == [
            ("item-a", "1"),
            ("item-a", "2"),
            ("item-b", "1"),
        ]
        assert result.rows[0]["attributes"] == {"title": None}
        assert [(request.path, request.param("page[number]")) for request in result.requests] == [
            ("/api/v2/items", "1"),
            (f"/api/v2/items/item-a/{endpoint}", "1"),
            (f"/api/v2/items/item-a/{endpoint}", "2"),
            (f"/api/v2/items/item-gone/{endpoint}", "1"),
            ("/api/v2/items", "2"),
            (f"/api/v2/items/item-b/{endpoint}", "1"),
        ]
        assert set(result.params("page[size]")) == {"100"}

    def test_fan_out_resumes_inside_the_item_in_progress(self) -> None:
        result = self._driver().run(
            "responses",
            route(
                {
                    "/api/v2/items": [_page([{"id": "item-a"}, {"id": "item-b"}, {"id": "item-c"}], next_link=None)],
                    "/api/v2/items/item-b/responses": [_page([{"id": "9"}], next_link=None)],
                    "/api/v2/items/item-c/responses": [_page([], next_link=None)],
                }
            ),
            resume_state=OpinionStageResumeConfig(
                fanout_state={
                    "completed": ["/api/v2/items/item-a/responses"],
                    "current": "/api/v2/items/item-b/responses",
                    "child_state": {"next_page": 3},
                }
            ),
        )

        assert result.raised is None
        assert [(row["item_id"], row["id"]) for row in result.rows] == [("item-b", "9")]
        assert [(request.path, request.param("page[number]")) for request in result.requests] == [
            ("/api/v2/items", "1"),
            ("/api/v2/items/item-b/responses", "3"),
            ("/api/v2/items/item-c/responses", "1"),
        ]
        assert result.committed_states

    @parameterized.expand(
        [
            ("next_link_without_counters", {"links": {"next": "p2"}}, ["1", "2"]),
            ("counters_without_next_link", {"meta": {"page": {"current": 1, "total": 2}}, "links": {}}, ["1", "2"]),
            ("last_page_by_counters", {"meta": {"page": {"current": 1, "total": 1}}}, ["1"]),
            ("malformed_counters", {"meta": {"page": {"current": "x"}}}, ["1"]),
            ("no_paging_fields", {}, ["1"]),
        ]
    )
    def test_next_page_signal(self, _name: str, envelope: dict[str, Any], expected_pages: list[str]) -> None:
        result = self._driver().run(
            "items",
            [ScriptedResponse(json={"data": [{"id": "1"}], **envelope}), _page([{"id": "2"}], next_link=None)][
                : len(expected_pages)
            ],
        )

        assert result.raised is None
        assert result.params("page[number]") == expected_pages

    def test_counters_stuck_on_page_1_stop_the_walk(self) -> None:
        stuck = {"meta": {"page": {"current": 1, "total": 5}}, "links": {}}
        result = self._driver().run(
            "items",
            always(ScriptedResponse(json={"data": [{"id": "1"}], **stuck})),
        )

        assert result.raised is None
        assert result.params("page[number]") == ["1", "2"]

    def test_empty_data_yields_no_rows(self) -> None:
        result = self._driver().run("items", [_page([], next_link=None)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.params("page[number]") == ["1"]
        assert result.saved_states == []

    def test_missing_data_key_is_retried_then_reraises(self) -> None:
        # A 200 body without a top-level `data` list is malformed for JSON:API; treat it as transient
        # and reissue rather than silently yielding nothing.
        result = self._driver().run("items", always(ScriptedResponse(json={"errors": [{"detail": "nope"}]})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_non_list_data_is_retried_then_reraises(self) -> None:
        result = self._driver().run("items", always(ScriptedResponse(json={"data": {"unexpected": "object"}})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand(
        [
            ("rate_limited", 429, "Too Many Requests"),
            ("server_error", 500, "Internal Server Error"),
            ("bad_gateway", 503, "Service Unavailable"),
        ]
    )
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, _reason: str) -> None:
        result = self._driver().run("items", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert f"HTTP {status}" in str(result.raised)
        assert len(result.requests) == 5

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    def test_client_error_raises_http_error_without_retry(self, _name: str, status: int, reason: str) -> None:
        # 4xx are credential/permission/shape failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        result = self._driver().run("items", [ScriptedResponse(status=status, json={"errors": ["denied"]})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error: {reason}" in str(result.raised)
        assert "https://api.opinionstage.com" in str(result.raised)
        assert len(result.requests) == 1

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = self._driver().run(endpoint, [_page([], next_link=None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        # JSON:API items carry no guaranteed stable creation timestamp column, so we don't partition.
        assert result.response.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, 200),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_status: int | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, returned_status = validate_credentials("os-key")

        assert ok is expected_ok
        assert returned_status == expected_status
        assert network.requests_log
        assert all(request.path == "/api/v2/items" for request in network.requests_log)
