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


def _small_charges_cfg(**overrides: Any) -> dict[str, Any]:
    """CHARGEDESK_ENDPOINTS override shrinking the charges page size (and optionally the offset cap)
    so pagination/window-shift behavior is testable with a handful of rows."""
    base = dataclasses.replace(CHARGEDESK_ENDPOINTS["charges"], **{"page_size": 2, **overrides})
    return {"charges": base}


def _response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"data": items}).encode()
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
    def test_single_short_page_is_terminal(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_charges([("a", 30), ("b", 20)]))])

        manager = _make_manager()
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(page_size=5)):
            rows = _rows(_source(manager=manager))

        assert [r["charge_id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1  # short page -> no next page
        manager.save_state.assert_not_called()

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
    def test_window_shift_at_offset_cap(self, MockSession) -> None:
        session = MockSession.return_value
        # max_offset=2 forces a window shift after each full page (offset would step to 2; 2+2 > 2).
        params = _wire(
            session,
            [
                _response(_charges([("a", 50), ("b", 40)])),
                _response(_charges([("b", 40), ("c", 30)])),
                _response(_charges([("c", 30), ("d", 20)])),
                _response(_charges([("d", 20)])),
            ],
        )

        manager = _make_manager()
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg(max_offset=2)):
            rows = _rows(_source(manager=manager))

        # Cap hit -> shift occurred[max] to oldest seen (40), reset offset 0.
        assert params[1]["offset"] == 0
        assert params[1]["occurred[max]"] == 40
        assert params[2]["occurred[max]"] == 30
        # First checkpoint records the shifted window.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == ChargedeskResumeConfig(offset=0, window_max=40, phase="full")
        # Every row is still surfaced (boundary rows re-fetched, deduped downstream on primary key).
        assert {r["charge_id"] for r in rows} == {"a", "b", "c", "d"}

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps({"error": "nope"}).encode()
        _wire(session, [resp])

        rows = _rows(_source())

        assert rows == []
        assert session.send.call_count == 1


class TestIncrementalPasses:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_scan_when_not_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_charges([("a", 50), ("b", 40), ("c", 30)]))])

        rows = _rows(_source(should_use_incremental_field=False))

        assert {r["charge_id"] for r in rows} == {"a", "b", "c"}
        # No incremental filters on a full scan.
        assert all("occurred[min]" not in p and "occurred[max]" not in p for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_latest_pass_uses_min_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_charges([("a", 50)]))])

        _rows(
            _source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=45,
                db_incremental_field_earliest_value=None,
            )
        )

        assert params[0]["occurred[min]"] == 45

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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_filter_param_differs_from_timestamp_field(self, MockSession) -> None:
        session = MockSession.return_value
        # Subscriptions filter on `created` but the row timestamp column is `first_seen`.
        params = _wire(session, [_response([{"subscription_id": "s1", "first_seen": 100}])])

        _rows(
            _source(
                endpoint="subscriptions",
                should_use_incremental_field=True,
                db_incremental_field_last_value=60,
            )
        )

        assert params[0]["created[min]"] == 60

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_ignored_for_full_refresh_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"product_id": "p1", "first_seen": 10}])])

        # products is full-refresh only, so the [min] filter must never be sent.
        _rows(
            _source(
                endpoint="products",
                should_use_incremental_field=True,
                db_incremental_field_last_value=5,
            )
        )

        assert all("created[min]" not in p for p in params)


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_from_saved_full_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_charges([("c", 30)]))])

        manager = _make_manager(ChargedeskResumeConfig(offset=2, window_max=None, phase="full"))
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            _rows(_source(manager=manager))

        # First fetch resumes from the saved offset, not 0.
        assert params[0]["offset"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_full_state_restores_window(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_charges([("c", 30)]))])

        manager = _make_manager(ChargedeskResumeConfig(offset=0, window_max=40, phase="full"))
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            _rows(_source(manager=manager))

        assert params[0]["offset"] == 0
        assert params[0]["occurred[max]"] == 40

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_mid_earliest_pass_then_runs_latest(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(_charges([("d", 15)])),  # resumed earliest backfill
                _response(_charges([("a", 60)])),  # latest pass
            ],
        )

        manager = _make_manager(ChargedeskResumeConfig(offset=2, window_max=18, phase="earliest"))
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            _rows(
                _source(
                    manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=50,
                    db_incremental_field_earliest_value=20,
                )
            )

        # Earliest pass resumes from the saved offset/window, not the earliest watermark.
        assert params[0]["offset"] == 2
        assert params[0]["occurred[max]"] == 18
        assert params[1]["occurred[min]"] == 50

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_latest_phase_skips_earliest_pass(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_charges([("a", 60)]))])

        manager = _make_manager(ChargedeskResumeConfig(offset=2, window_max=None, phase="latest"))
        with mock.patch.dict(CHARGEDESK_ENDPOINTS, _small_charges_cfg()):
            _rows(
                _source(
                    manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=50,
                    db_incremental_field_earliest_value=20,
                )
            )

        # A single request: the earliest backfill already completed, only the latest pass resumes.
        assert session.send.call_count == 1
        assert params[0]["offset"] == 2
        assert params[0]["occurred[min]"] == 50
        assert "occurred[max]" not in params[0]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with mock.patch(CHARGEDESK_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
            assert validate_credentials("sk_test") is expected

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(CHARGEDESK_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("sk_test") is False


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

    def test_primary_keys_are_resource_specific(self) -> None:
        assert _source(endpoint="charges").primary_keys == ["charge_id"]
        assert _source(endpoint="customers").primary_keys == ["customer_id"]


if __name__ == "__main__":
    pytest.main([__file__])
