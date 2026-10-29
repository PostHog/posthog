from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.livestorm import (
    LivestormSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.livestorm.livestorm import LivestormResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.livestorm.source import LivestormSource

API_TOKEN = "test-livestorm-token"


def _driver() -> SourceDriver:
    return SourceDriver(LivestormSource(), LivestormSourceConfig(api_token=API_TOKEN))


def _item(item_id: str, **attributes: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "events",
        "attributes": {"updated_at": 1760000000, **attributes},
        "relationships": {"sessions": {"data": []}},
    }


def _page(items: list[dict[str, Any]], page_count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "meta": {"page_count": page_count, "record_count": 3}})


class TestLivestormLists:
    def test_walks_pages_until_the_last_page_count(self) -> None:
        result = _driver().run(
            "events",
            [
                _page([_item("e1", title="Launch"), _item("e2", title="Demo")], page_count=2),
                _page([_item("e3", title="Q&A")], page_count=2),
            ],
        )

        assert result.raised is None
        assert result.params("page[number]") == ["0", "1"]
        assert result.params("page[size]") == ["50", "50"]
        assert {r.headers.get("authorization") for r in result.requests} == {API_TOKEN}
        assert result.rows[0] == {"id": "e1", "updated_at": 1760000000, "title": "Launch"}
        assert result.saved_states == [LivestormResumeConfig(next_page=1)]

    def test_resume_starts_from_the_saved_page(self) -> None:
        result = _driver().run(
            "sessions", [_page([_item("s9")], page_count=5)], resume_state=LivestormResumeConfig(next_page=4)
        )

        assert result.params("page[number]") == ["4"]

    @parameterized.expand(
        [
            (
                "incremental",
                {"incremental_field": "updated_at", "db_incremental_field_last_value": 1759000000},
                "1759000000",
                "desc",
            ),
            ("full_refresh", {}, None, "asc"),
        ]
    )
    def test_incremental_filter_and_sort_mode(
        self, _name: str, inputs: dict[str, Any], expected_filter: str | None, expected_sort: str
    ) -> None:
        result = _driver().run("sessions", [_page([_item("s1")], page_count=1)], **inputs)

        assert result.requests[0].param("filter[updated_since]") == expected_filter
        assert result.response is not None
        assert result.response.sort_mode == expected_sort


class TestLivestormSessionPeople:
    def test_fans_out_per_session_and_keys_rows_by_session(self) -> None:
        result = _driver().run(
            "session_people",
            route(
                {
                    "/v1/sessions": [_page([_item("s1"), _item("s2")], page_count=1)],
                    "/v1/sessions/s1/people": [
                        _page([_item("p1", email="a@example.com")], page_count=2),
                        _page([_item("p2", email="b@example.com")], page_count=2),
                    ],
                    "/v1/sessions/s2/people": [_page([_item("p1", email="a@example.com")], page_count=1)],
                }
            ),
            incremental_field="updated_at",
            db_incremental_field_last_value=1759000000,
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/sessions",
            "/v1/sessions/s1/people",
            "/v1/sessions/s1/people",
            "/v1/sessions/s2/people",
        ]
        assert result.requests[0].param("filter[updated_since]") is None
        # Every session is read. Livestorm documents no session filter that catches a new
        # registration or replay view on an older session.
        assert result.requests[0].param("filter[date_from]") is None
        assert {r.param("filter[updated_since]") for r in result.requests[1:]} == {"1759000000"}
        assert [(row["session_id"], row["id"]) for row in result.rows] == [("s1", "p1"), ("s1", "p2"), ("s2", "p1")]
        assert all("attributes" not in row and "_sessions_id" not in row for row in result.rows)

    def test_resume_skips_sessions_already_read(self) -> None:
        result = _driver().run(
            "session_people",
            route(
                {
                    "/v1/sessions": [_page([_item("s1"), _item("s2")], page_count=1)],
                    "/v1/sessions/s2/people": [_page([_item("p3")], page_count=1)],
                }
            ),
            resume_state=LivestormResumeConfig(
                fanout_state={"completed": ["/sessions/s1/people"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/sessions", "/v1/sessions/s2/people"]
