from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepagecrm import (
    OnepagecrmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm import (
    OnepagecrmResumeConfig,
    _to_epoch,
    modified_since_anchor,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ENDPOINTS,
    ONEPAGECRM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source import OnepagecrmSource


def _driver() -> SourceDriver:
    return SourceDriver(OnepagecrmSource(), OnepagecrmSourceConfig(user_id="uid", api_key="key"))


def _list_page(
    data_key: str,
    item_key: str,
    records: list[dict[str, Any]],
    page: int,
    max_page: int | None,
) -> ScriptedResponse:
    data: dict[str, Any] = {
        data_key: [{item_key: record} for record in records],
        "total_count": len(records),
        "page": page,
        "per_page": 100,
    }
    if max_page is not None:
        data["max_page"] = max_page
    return ScriptedResponse(json={"status": 0, "message": "OK", "data": data})


class TestToEpoch:
    @parameterized.expand(
        [
            (None, None),
            (True, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-timestamp", None),
        ],
    )
    def test_to_epoch_values(self, value: Any, expected: int | None) -> None:
        assert _to_epoch(value) == expected

    def test_anchor_backs_off_one_second(self) -> None:
        assert modified_since_anchor(1700000000) == "1699999999"
        assert modified_since_anchor(None) is None


class TestPagination:
    def test_incremental_run_pins_anchor_across_pages(self) -> None:
        result = _driver().run(
            "deals",
            [
                _list_page("deals", "deal", [{"id": "d1"}], page=1, max_page=2),
                _list_page("deals", "deal", [{"id": "d2"}], page=2, max_page=2),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("modified_since") == ["1699999999", "1699999999"]
        assert result.params("sort_by") == ["modified_at", "modified_at"]
        assert result.saved_states == [OnepagecrmResumeConfig(page=2, modified_since="1699999999")]

    def test_resumes_from_saved_page_and_saved_anchor(self) -> None:
        result = _driver().run(
            "deals",
            [_list_page("deals", "deal", [{"id": "d9"}], page=5, max_page=5)],
            resume_state=OnepagecrmResumeConfig(page=5, modified_since="1600000000"),
            should_use_incremental_field=True,
            # A fresher watermark must NOT replace the saved anchor: page numbers are only
            # stable for the query the run started with.
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("page") == ["5"]
        assert result.params("modified_since") == ["1600000000"]

    def test_short_page_terminates_when_max_page_missing(self) -> None:
        result = _driver().run(
            "contacts",
            [_list_page("contacts", "contact", [{"id": "a1"}], page=1, max_page=None)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1"]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_empty_first_page_stops_without_state(self) -> None:
        result = _driver().run("contacts", [_list_page("contacts", "contact", [], page=1, max_page=1)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("users", {"data": [{"user": {"id": "u1"}}, {"user": {"id": "u2"}}]}, ["u1", "u2"]),
            ("statuses", {"data": [{"status": {"id": "s1"}}]}, ["s1"]),
            ("lead_sources", {"data": [{"id": "advertisement"}, {"id": "web"}]}, ["advertisement", "web"]),
        ]
    )
    def test_config_endpoints_yield_bare_array_records(
        self, endpoint: str, body: dict[str, Any], expected_ids: list[str]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert len(result.requests) == 1

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("contacts", [ScriptedResponse(json={"status": 0, "message": "OK"})])

        # A 200 body missing the data list means the response shape changed — fail loud.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestOnepagecrmSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = ONEPAGECRM_ENDPOINTS[endpoint]
        body: dict[str, Any] = {"data": {config.data_key: []} if config.paginated else []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(name,) for name, c in ONEPAGECRM_ENDPOINTS.items() if c.partition_key])
    def test_partition_keys_are_stable_creation_fields(self, endpoint: str) -> None:
        assert ONEPAGECRM_ENDPOINTS[endpoint].partition_key == "created_at"
