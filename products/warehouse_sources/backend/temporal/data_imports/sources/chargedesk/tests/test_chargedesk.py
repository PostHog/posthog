import dataclasses
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.chargedesk import (
    ChargedeskResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import CHARGEDESK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.source import ChargedeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargedesk import (
    ChargedeskSourceConfig,
)


def _small_charges_cfg(**overrides: Any) -> dict[str, Any]:
    """Shrink the page size and optional offset cap for pagination tests."""
    return {"charges": dataclasses.replace(CHARGEDESK_ENDPOINTS["charges"], **{"page_size": 2, **overrides})}


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items})


def _items_response(items: list[dict[str, Any]]) -> ScriptedResponse:
    # The charge items endpoint answers with two arrays; only `items` is synced.
    return ScriptedResponse(json={"items": items, "taxes": []})


def _charges(ids_and_ts: list[tuple[str, int]]) -> list[dict[str, Any]]:
    # Newest first, matching ChargeDesk's default list ordering.
    return [{"charge_id": cid, "occurred": ts} for cid, ts in ids_and_ts]


def _driver() -> SourceDriver:
    return SourceDriver(ChargedeskSource(), ChargedeskSourceConfig(api_key="sk_test"))


class TestPagination:
    def test_multi_page_offsets_and_termination(self) -> None:
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            result = _driver().run(
                "charges",
                [
                    _response(_charges([("a", 50), ("b", 40)])),
                    _response(_charges([("c", 30), ("d", 20)])),
                    _response(_charges([("e", 10)])),
                ],
            )

        # 5 rows / page_size 2 => full pages [a,b],[c,d] then terminal short page [e]
        assert result.raised is None
        assert [row["charge_id"] for row in result.rows] == ["a", "b", "c", "d", "e"]
        assert result.params("offset") == ["0", "2", "4"]
        assert result.params("count") == ["2", "2", "2"]
        # Checkpoints save the NEXT page to fetch, tagged with the current phase; terminal page saves nothing.
        assert result.saved_states[0] == ChargedeskResumeConfig(offset=2, window_max=None, phase="full")
        assert all(state.phase == "full" for state in result.saved_states)

    def test_stops_when_offset_cap_window_collapses_to_one_timestamp(self) -> None:
        # More rows than the offset cap can reach all share the same timestamp. Re-pinning [max] to that
        # timestamp would re-fetch the same page forever; pagination must terminate instead of spinning.
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(max_offset=2)):
            result = _driver().run(
                "charges",
                [
                    _response(_charges([("a", 100), ("b", 100)])),
                    _response(_charges([("a", 100), ("b", 100)])),
                ],
            )

        # It shifted [max] to 100 exactly once, then stopped on the next identical-timestamp page.
        assert result.raised is None
        assert len(result.requests) == 2
        assert result.requests[1].param("occurred[max]") == "100"

    def test_stops_at_offset_cap_without_usable_timestamp(self) -> None:
        # Can't shift the window without a timestamp to anchor it; stepping past the cap would 400.
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(max_offset=2)):
            result = _driver().run("charges", [_response([{"charge_id": "a"}, {"charge_id": "b"}])])

        assert result.raised is None
        assert len(result.requests) == 1
        assert [row["charge_id"] for row in result.rows] == ["a", "b"]


class TestIncrementalPasses:
    def test_earliest_pass_then_latest_pass(self) -> None:
        result = _driver().run(
            "charges",
            [
                _response(_charges([("d", 20)])),  # earliest backfill
                _response(_charges([("a", 60)])),  # latest pass
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=50,
            db_incremental_field_earliest_value=20,
        )

        # Earliest backfill runs first with occurred[max]=20, then latest with occurred[min]=50.
        assert result.raised is None
        assert result.requests[0].param("occurred[max]") == "20"
        assert result.requests[0].param("occurred[min]") is None
        assert result.requests[1].param("occurred[min]") == "50"
        assert result.requests[1].param("occurred[max]") is None


class TestChargeItemsFanout:
    def test_incremental_bounds_the_parent_walk(self) -> None:
        result = _driver().run(
            "charge_items",
            [_response(_charges([("a", 60)])), _items_response([{"ord": 0}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=50,
        )

        # The child takes no filters, so the watermark has to narrow the parent listing instead.
        assert result.raised is None
        assert result.requests[0].path == "/v1/charges"
        assert result.requests[0].param("occurred[min]") == "50"
        assert result.requests[1].path == "/v1/charges/a/items"
        assert result.queries[1] == {}


class TestSyntheticLogIds:
    def test_indistinguishable_rows_collapse_within_a_page(self) -> None:
        entry = {"object_type": "charge", "object_id": "a", "event": "charge-refund", "occurred": 100}
        result = _driver().run("activity_log", [_response([entry, dict(entry), {**entry, "event": "charge-void"}])])

        assert result.raised is None
        assert [row["event"] for row in result.rows] == ["charge-refund", "charge-void"]
        assert len({row["log_id"] for row in result.rows}) == 2


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            assert validate_credentials("sk_test") is expected

        assert network.requests_log[0].path == "/v1/charges"
        assert network.requests_log[0].param("count") == "1"


class TestChargedeskSource:
    @parameterized.expand(list(CHARGEDESK_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        cfg = CHARGEDESK_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == cfg.primary_keys
        # ChargeDesk returns rows newest-first.
        assert result.response.sort_mode == "desc"
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == [cfg.timestamp_field]


if __name__ == "__main__":
    pytest.main([__file__])
