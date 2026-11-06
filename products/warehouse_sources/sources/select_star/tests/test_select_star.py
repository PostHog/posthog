from datetime import UTC, datetime
from typing import Any, Optional

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network
from products.warehouse_sources.sources.select_star._config import SelectStarSourceConfig
from products.warehouse_sources.sources.select_star.select_star import SelectStarResumeConfig, validate_credentials
from products.warehouse_sources.sources.select_star.settings import ENDPOINTS, SELECTSTAR_BASE_URL, SELECTSTAR_ENDPOINTS
from products.warehouse_sources.sources.select_star.source import SelectStarSource

TABLES_URL = f"{SELECTSTAR_BASE_URL}/v1/tables/"
TAGS_URL = f"{SELECTSTAR_BASE_URL}/v1/tags/"


def _driver() -> SourceDriver:
    return SourceDriver(SelectStarSource(), SelectStarSourceConfig(api_token="tok"))


def _page(results: list[dict[str, Any]], *, next_url: Optional[str] = None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(results), "next": next_url, "previous": None, "results": results})


class TestPagination:
    def test_follows_next_url_until_null(self) -> None:
        second = f"{TABLES_URL}?page=2"

        result = _driver().run("Tables", [_page([{"guid": "a"}], next_url=second), _page([{"guid": "b"}])])

        assert result.rows == [{"guid": "a"}, {"guid": "b"}]
        assert result.urls[0].split("?")[0] == TABLES_URL
        assert result.urls[1] == second
        assert result.saved_states == [SelectStarResumeConfig(next_url=second)]

    def test_resumes_from_the_saved_cursor(self) -> None:
        saved = f"{TABLES_URL}?page=7"

        result = _driver().run("Tables", [_page([{"guid": "z"}])], resume_state=SelectStarResumeConfig(next_url=saved))

        assert result.rows == [{"guid": "z"}]
        assert result.urls == [saved]


class TestIncrementalFilter:
    def test_default_incremental_field_used_when_none_selected(self) -> None:
        result = _driver().run(
            "Tables",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("updated_on__gte") == "2026-01-01 00:00:00+00:00"


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert validate_credentials("tok") == (True, None)

        assert network.requests_log[0].headers["authorization"] == "Token tok"


class TestSelectStarSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS if SELECTSTAR_ENDPOINTS[e].fanout is None])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["guid"]
        assert result.response.sort_mode == "asc"


def _lineage(nodes: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"table_lineage": nodes, "column_lineage": []})


class TestFanout:
    @parameterized.expand(
        [
            (
                "lineage",
                "Lineage",
                "/v1/tables/",
                "/v1/lineage/{}/",
                "table_guid",
                _lineage([{"key": "ta_1", "guid": "ta_1"}]),
            ),
            (
                "dashboard_frequent_users",
                "DashboardFrequentUsers",
                "/v1/bi/dashboards/",
                "/v1/bi/dashboards/{}/frequent-dsusers/",
                "dashboard_guid",
                _page([{"guid": "du_1", "query_count": 7}]),
            ),
            (
                "tagged_items",
                "TaggedItems",
                "/v1/tags/",
                "/v1/tags/items/{}/",
                "tag_guid",
                _page([{"kind": "user-defined", "item": {"object_type": "column", "obj": {"guid": "co_1"}}}]),
            ),
        ]
    )
    def test_walks_every_parent_page_and_tags_child_rows(
        self,
        _name: str,
        endpoint: str,
        parent_path: str,
        child_path: str,
        parent_key: str,
        child_response: ScriptedResponse,
    ) -> None:
        parent_page_2 = f"{SELECTSTAR_BASE_URL}{parent_path}?page=2"

        result = _driver().run(
            endpoint,
            [
                _page([{"guid": "p1"}, {"guid": "p2"}], next_url=parent_page_2),
                child_response,
                child_response,
                _page([{"guid": "p3"}]),
                child_response,
            ],
        )

        assert result.paths == [
            parent_path,
            child_path.format("p1"),
            child_path.format("p2"),
            parent_path,
            child_path.format("p3"),
        ]
        assert [row[parent_key] for row in result.rows] == ["p1", "p2", "p3"]
        assert result.requests[0].param("page_size") == "100"
        assert all(request.param("page_size") is None for request in result.requests[1:3])
        assert result.response is not None
        assert result.response.primary_keys == SELECTSTAR_ENDPOINTS[endpoint].primary_keys
        assert all(key in result.rows[0] for key in result.response.primary_keys)
        assert result.response.sort_mode is None

    def test_lineage_requests_one_level_of_downstream_table_lineage(self) -> None:
        result = _driver().run("Lineage", [_page([{"guid": "ta_root"}]), _lineage([])])

        child = result.requests[1]
        assert (child.param("max_depth"), child.param("direction"), child.param("mode")) == ("1", "right", "table")

    def test_tagged_items_flatten_the_tagged_asset(self) -> None:
        result = _driver().run(
            "TaggedItems",
            [
                _page([{"guid": "tg_1"}]),
                _page(
                    [
                        {"kind": "suggested", "item": {"object_type": "table", "obj": {"guid": "ta_1"}}},
                        {"kind": "user-defined", "item": None},
                    ]
                ),
            ],
        )

        assert [(r["item_guid"], r["item_object_type"]) for r in result.rows] == [("ta_1", "table"), (None, None)]

    def test_follows_child_next_url_and_skips_a_deleted_parent(self) -> None:
        child_page_2 = f"{SELECTSTAR_BASE_URL}/v1/bi/dashboards/da_1/frequent-dsusers/?page=2"

        result = _driver().run(
            "DashboardFrequentUsers",
            [
                _page([{"guid": "da_gone"}, {"guid": "da_1"}]),
                ScriptedResponse(status=404, body=b"Not Found"),
                _page([{"guid": "du_1"}], next_url=child_page_2),
                _page([{"guid": "du_2"}]),
            ],
        )

        assert [(r["dashboard_guid"], r["guid"]) for r in result.rows] == [("da_1", "du_1"), ("da_1", "du_2")]
        assert result.urls[-1] == child_page_2

    def test_resumes_from_saved_fanout_state(self) -> None:
        first = _driver().run(
            "DashboardFrequentUsers",
            [
                _page([{"guid": "da_1"}, {"guid": "da_2"}]),
                _page([{"guid": "du_1"}]),
                _page([{"guid": "du_2"}]),
            ],
        )
        assert first.saved_states
        saved = first.saved_states[0]
        assert isinstance(saved, SelectStarResumeConfig) and saved.fanout_state is not None

        resumed = _driver().run(
            "DashboardFrequentUsers",
            [_page([{"guid": "da_1"}, {"guid": "da_2"}]), _page([{"guid": "du_2"}])],
            resume_state=saved,
        )

        assert resumed.paths == ["/v1/bi/dashboards/", "/v1/bi/dashboards/da_2/frequent-dsusers/"]
        assert [r["guid"] for r in resumed.rows] == ["du_2"]
