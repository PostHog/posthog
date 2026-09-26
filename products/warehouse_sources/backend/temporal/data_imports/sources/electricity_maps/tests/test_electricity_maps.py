import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.electricity_maps import (
    ElectricityMapsResumeConfig,
    electricity_maps_source,
    initial_window_start,
    invalid_zones,
    parse_zones,
    validate_credentials,
)

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(zone: str) -> Response:
    return _make_http_response(
        {"zone": zone, "data": [{"zone": zone, "carbonIntensity": 300, "datetime": "2025-06-10T00:00:00.000Z"}]}
    )


def _drive(
    *,
    manager: MagicMock,
    responses: list[Response],
    zones: list[str],
    endpoint: str = "carbon_intensity",
    incremental: bool = False,
    last_value: Any = None,
    history_days: int | None = None,
) -> list[dict[str, Any]]:
    # Capture shallow copies of request.params at send time: the paginator mutates the one
    # Request object in place between pages, so call_args_list would only show the final state.
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        response = electricity_maps_source(
            api_token="test-token",
            zones=zones,
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=incremental,
            history_days=history_days,
        )
        list(cast(Iterable[Any], response.items()))
    return sent_params


def _fresh_manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestZoneParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("DE", ["DE"]),
            ("de, dk-dk1 ,DE", ["DE", "DK-DK1"]),
            (" , ,", []),
            ("US-CAL-CISO", ["US-CAL-CISO"]),
        ],
    )
    def test_parse_zones_normalizes_and_dedupes(self, raw: str, expected: list[str]) -> None:
        assert parse_zones(raw) == expected

    @pytest.mark.parametrize(
        ("zones", "expected_invalid"),
        [
            (["DE", "DK-DK1"], []),
            (["HTTPS://EXAMPLE.COM", "DE"], ["HTTPS://EXAMPLE.COM"]),
            (["DE DE"], ["DE DE"]),
        ],
    )
    def test_invalid_zones_flags_non_zone_values(self, zones: list[str], expected_invalid: list[str]) -> None:
        assert invalid_zones(zones) == expected_invalid


class TestInitialWindowStart:
    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (datetime(2025, 6, 10, 3, 0, 0, tzinfo=UTC), datetime(2025, 6, 10, 3, 0, 0, tzinfo=UTC)),
            # A naive watermark from the DB is treated as UTC rather than rejected.
            (datetime(2025, 6, 10, 3, 0, 0), datetime(2025, 6, 10, 3, 0, 0, tzinfo=UTC)),
            ("2025-06-10T03:00:00+00:00", datetime(2025, 6, 10, 3, 0, 0, tzinfo=UTC)),
            (None, datetime(2025, 6, 5, 12, 0, 0, tzinfo=UTC)),
            # An unparseable watermark falls back to the history window instead of crashing the sync.
            ("not-a-datetime", datetime(2025, 6, 5, 12, 0, 0, tzinfo=UTC)),
        ],
    )
    def test_start_comes_from_watermark_or_history_window(self, last_value: Any, expected: datetime) -> None:
        assert initial_window_start(last_value, history_days=10, now=_NOW) == expected


class TestWindowWalk:
    @time_machine.travel(_NOW, tick=False)
    def test_walks_window_major_across_zones_and_clamps_final_window(self) -> None:
        manager = _fresh_manager()
        watermark = datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC)

        sent_params = _drive(
            manager=manager,
            responses=[_page("DE"), _page("SE"), _page("DE"), _page("SE")],
            zones=["DE", "SE"],
            incremental=True,
            last_value=watermark,
        )

        assert [(p["zone"], p["start"], p["end"]) for p in sent_params] == [
            ("DE", "2025-06-07T12:00:00Z", "2025-06-12T12:00:00Z"),
            ("SE", "2025-06-07T12:00:00Z", "2025-06-12T12:00:00Z"),
            ("DE", "2025-06-12T12:00:00Z", "2025-06-15T12:00:00Z"),
            ("SE", "2025-06-12T12:00:00Z", "2025-06-15T12:00:00Z"),
        ]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ElectricityMapsResumeConfig(window_start="2025-06-07T12:00:00Z", zone_index=1),
            ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=0),
            ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=1),
        ]

    @time_machine.travel(_NOW, tick=False)
    def test_watermark_at_or_past_now_still_requests_one_valid_window(self) -> None:
        manager = _fresh_manager()

        sent_params = _drive(
            manager=manager,
            responses=[_page("DE")],
            zones=["DE"],
            incremental=True,
            last_value=datetime(2025, 6, 15, 13, 0, 0, tzinfo=UTC),
        )

        assert sent_params == [{"zone": "DE", "start": "2025-06-15T11:00:00Z", "end": "2025-06-15T12:00:00Z"}]
        manager.save_state.assert_not_called()

    @time_machine.travel(_NOW, tick=False)
    @pytest.mark.parametrize(
        ("history_days", "expected_start"),
        [
            (None, "2025-05-16T12:00:00Z"),
            (7, "2025-06-08T12:00:00Z"),
        ],
    )
    def test_full_refresh_starts_at_history_window_and_ignores_watermark(
        self, history_days: int | None, expected_start: str
    ) -> None:
        sent_params = _drive(
            manager=_fresh_manager(),
            responses=[_page("DE")] * 10,
            zones=["DE"],
            incremental=False,
            last_value=datetime(2025, 6, 14, 0, 0, 0, tzinfo=UTC),
            history_days=history_days,
        )

        assert sent_params[0]["start"] == expected_start

    @time_machine.travel(_NOW, tick=False)
    def test_resume_seeds_window_and_zone(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=1)

        sent_params = _drive(
            manager=manager,
            responses=[_page("SE")],
            zones=["DE", "SE"],
            incremental=True,
            last_value=datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC),
        )

        assert sent_params == [{"zone": "SE", "start": "2025-06-12T12:00:00Z", "end": "2025-06-15T12:00:00Z"}]

    @time_machine.travel(_NOW, tick=False)
    def test_resume_with_out_of_range_zone_index_falls_back_to_first_zone(self) -> None:
        # The zone list is user-editable between a save and a resume, so a stale index must not crash.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=5)

        sent_params = _drive(
            manager=manager,
            responses=[_page("DE"), _page("SE")],
            zones=["DE", "SE"],
            incremental=True,
            last_value=datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC),
        )

        assert [p["zone"] for p in sent_params] == ["DE", "SE"]

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Electricity Maps endpoint"):
            electricity_maps_source(
                api_token="test-token",
                zones=["DE"],
                endpoint="forecast",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=_fresh_manager(),
                db_incremental_field_last_value=None,
            )

    def test_no_zones_raises(self) -> None:
        with pytest.raises(ValueError, match="zones"):
            electricity_maps_source(
                api_token="test-token",
                zones=[],
                endpoint="carbon_intensity",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=_fresh_manager(),
                db_incremental_field_last_value=None,
            )


class TestValidateCredentials:
    _SESSION = (
        "products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.electricity_maps"
        ".make_tracked_session"
    )

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (200, True, None),
            (401, False, "rejected your API token"),
            (403, False, "does not have access to zone DE"),
            (404, False, "does not recognize zone DE"),
            (500, False, "unexpected status code (500)"),
        ],
    )
    def test_status_maps_to_user_message(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        with patch(self._SESSION) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code=status_code)
            is_valid, message = validate_credentials("test-token", ["DE"])

        assert is_valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message

    def test_stops_at_first_failing_zone(self) -> None:
        with patch(self._SESSION) as MockSession:
            MockSession.return_value.get.side_effect = [
                _make_http_response({}, status_code=200),
                _make_http_response({}, status_code=403),
            ]
            is_valid, message = validate_credentials("test-token", ["DE", "XX"])

        assert is_valid is False
        assert message is not None and "zone XX" in message
