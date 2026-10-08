import json
import dataclasses
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.chargedesk import (
    ChargedeskResumeConfig,
    chargedesk_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import CHARGEDESK_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the chargedesk module.
CHARGEDESK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.chargedesk.make_tracked_session"
)


def _small_cfg(endpoint: str, **overrides: Any) -> dict[str, Any]:
    """CHARGEDESK_ENDPOINTS override shrinking an endpoint's page size (and optionally the offset cap)
    so pagination/window-shift behavior is testable with a handful of rows."""
    return {endpoint: dataclasses.replace(CHARGEDESK_ENDPOINTS[endpoint], **{"page_size": 2, **overrides})}


def _small_charges_cfg(**overrides: Any) -> dict[str, Any]:
    return _small_cfg("charges", **overrides)


def _response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"data": items}).encode()
    return resp


def _items_response(items: list[dict[str, Any]]) -> Response:
    # The charge items endpoint answers with two arrays; only `items` is synced.
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"items": items, "taxes": []}).encode()
    return resp


def _charges(ids_and_ts: list[tuple[str, int]]) -> list[dict[str, Any]]:
    # Newest first, matching ChargeDesk's default list ordering.
    return [{"charge_id": cid, "occurred": ts} for cid, ts in ids_and_ts]


def _make_manager(resume_state: ChargedeskResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_requests(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Like `_wire`, but snapshots each request's URL alongside its params at send time."""
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str = "charges",
    manager: mock.MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_earliest_value: Any = None,
):
    return chargedesk_source(
        api_key="sk_test",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        logger=mock.MagicMock(),
        resumable_source_manager=manager if manager is not None else _make_manager(),
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=db_incremental_field_earliest_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_multi_page_offsets_and_termination(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_charges([("a", 50), ("b", 40)])),
                _response(_charges([("c", 30), ("d", 20)])),
                _response(_charges([("e", 10)])),
            ],
        )

        manager = _make_manager()
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            rows = _rows(_source(manager=manager))

        # 5 rows / page_size 2 => full pages [a,b],[c,d] then terminal short page [e]
        assert [r["charge_id"] for r in rows] == ["a", "b", "c", "d", "e"]
        assert [p["offset"] for p in params] == [0, 2, 4]
        assert all(p["count"] == 2 for p in params)
        # Checkpoints save the NEXT page to fetch, tagged with the current phase; terminal page saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == ChargedeskResumeConfig(offset=2, window_max=None, phase="full")
        assert all(s.phase == "full" for s in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_offset_cap_window_collapses_to_one_timestamp(self, MockSession) -> None:
        session = MockSession.return_value
        # More rows than the offset cap can reach all share the same timestamp. Re-pinning [max] to that
        # timestamp would re-fetch the same page forever; pagination must terminate instead of spinning.
        params = _wire(
            session,
            [
                _response(_charges([("a", 100), ("b", 100)])),
                _response(_charges([("a", 100), ("b", 100)])),
            ],
        )

        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(max_offset=2)):
            _rows(_source())

        # It shifted [max] to 100 exactly once, then stopped on the next identical-timestamp page.
        assert session.send.call_count == 2
        assert params[1]["occurred[max]"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_offset_cap_without_usable_timestamp(self, MockSession) -> None:
        session = MockSession.return_value
        # Can't shift the window without a timestamp to anchor it; stepping past the cap would 400.
        _wire(session, [_response([{"charge_id": "a"}, {"charge_id": "b"}])])

        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(max_offset=2)):
            rows = _rows(_source())

        assert session.send.call_count == 1
        assert [r["charge_id"] for r in rows] == ["a", "b"]


class TestIncrementalPasses:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_earliest_pass_then_latest_pass(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_charges([("d", 20)])),  # earliest backfill
                _response(_charges([("a", 60)])),  # latest pass
            ],
        )

        _rows(
            _source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=50,
                db_incremental_field_earliest_value=20,
            )
        )

        # Earliest backfill runs first with occurred[max]=20, then latest with occurred[min]=50.
        assert params[0].get("occurred[max]") == 20
        assert "occurred[min]" not in params[0]
        assert params[1].get("occurred[min]") == 50
        assert "occurred[max]" not in params[1]


class TestChargeItemsFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_bounds_the_parent_walk(self, MockSession) -> None:
        session = MockSession.return_value
        requests = _wire_requests(
            session,
            [_response(_charges([("a", 60)])), _items_response([{"ord": 0}])],
        )

        _rows(
            _source(
                endpoint="charge_items",
                should_use_incremental_field=True,
                db_incremental_field_last_value=50,
            )
        )

        # The child takes no filters, so the watermark has to narrow the parent listing instead.
        assert requests[0][1]["occurred[min]"] == 50
        assert requests[1][1] == {}


class TestSyntheticLogIds:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_indistinguishable_rows_collapse_within_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        entry = {"object_type": "charge", "object_id": "a", "event": "charge-refund", "occurred": 100}
        _wire(session, [_response([entry, dict(entry), {**entry, "event": "charge-void"}])])

        rows = _rows(_source(endpoint="activity_log"))

        assert [r["event"] for r in rows] == ["charge-refund", "charge-void"]
        assert len({r["log_id"] for r in rows}) == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with mock.patch(CHARGEDESK_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
            assert validate_credentials("sk_test") is expected


class TestChargedeskSource:
    @parameterized.expand(list(CHARGEDESK_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        cfg = CHARGEDESK_ENDPOINTS[endpoint]
        response = _source(endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # ChargeDesk returns rows newest-first.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [cfg.timestamp_field]


if __name__ == "__main__":
    pytest.main([__file__])
