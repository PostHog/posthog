from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.electricity_maps import (
    ElectricityMapsResumeConfig,
    initial_window_start,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.electricity_maps.source import (
    ElectricityMapsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _page(zone: str) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "zone": zone,
            "data": [{"zone": zone, "carbonIntensity": 300, "datetime": "2025-06-10T00:00:00.000Z"}],
        }
    )


def _driver(zones: str = "DE", history_days: int | None = None, pricing_nodes: str | None = None) -> SourceDriver:
    return SourceDriver(
        ElectricityMapsSource(),
        ElectricityMapsSourceConfig(
            api_token="test-token", zones=zones, history_days=history_days, pricing_nodes=pricing_nodes
        ),
    )


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
        watermark = datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC)

        result = _driver("DE, SE").run(
            "carbon_intensity",
            [_page("DE"), _page("SE"), _page("DE"), _page("SE")],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert [
            (request.param("zone"), request.param("start"), request.param("end")) for request in result.requests
        ] == [
            ("DE", "2025-06-07T12:00:00Z", "2025-06-12T12:00:00Z"),
            ("SE", "2025-06-07T12:00:00Z", "2025-06-12T12:00:00Z"),
            ("DE", "2025-06-12T12:00:00Z", "2025-06-15T12:00:00Z"),
            ("SE", "2025-06-12T12:00:00Z", "2025-06-15T12:00:00Z"),
        ]

        assert result.saved_states == [
            ElectricityMapsResumeConfig(window_start="2025-06-07T12:00:00Z", zone_index=1),
            ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=0),
            ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=1),
        ]

    @time_machine.travel(_NOW, tick=False)
    @pytest.mark.parametrize(
        ("endpoint", "entity_param", "entity"),
        [
            ("carbon_intensity", "zone", "DE"),
            # Locational marginal prices are addressed by pricing node; the API rejects a zone.
            ("locational_marginal_price_day_ahead", "node", "CORTINA_1_N106"),
        ],
    )
    def test_watermark_at_or_past_now_still_requests_one_valid_window(
        self, endpoint: str, entity_param: str, entity: str
    ) -> None:
        result = _driver(pricing_nodes="CORTINA_1_N106").run(
            endpoint,
            [_page("DE")],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 15, 13, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.queries == [
            {entity_param: (entity,), "start": ("2025-06-15T11:00:00Z",), "end": ("2025-06-15T12:00:00Z",)}
        ]
        assert result.saved_states == []

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
        result = _driver(history_days=history_days).run(
            "carbon_intensity",
            always(_page("DE")),
            db_incremental_field_last_value=datetime(2025, 6, 14, 0, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("start") == expected_start

    @time_machine.travel(_NOW, tick=False)
    def test_resume_seeds_window_and_zone(self) -> None:
        result = _driver("DE, SE").run(
            "carbon_intensity",
            [_page("SE")],
            resume_state=ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=1),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.queries == [
            {"zone": ("SE",), "start": ("2025-06-12T12:00:00Z",), "end": ("2025-06-15T12:00:00Z",)}
        ]

    @time_machine.travel(_NOW, tick=False)
    def test_resume_with_out_of_range_zone_index_falls_back_to_first_zone(self) -> None:
        # The zone list is user-editable between a save and a resume, so a stale index must not crash.
        result = _driver("DE, SE").run(
            "carbon_intensity",
            [_page("DE"), _page("SE")],
            resume_state=ElectricityMapsResumeConfig(window_start="2025-06-12T12:00:00Z", zone_index=5),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 7, 12, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("zone") == ["DE", "SE"]

    def test_unknown_endpoint_raises(self) -> None:
        result = _driver().run("forecast", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Electricity Maps endpoint" in str(result.raised)

    @pytest.mark.parametrize(
        ("endpoint", "zones", "pricing_nodes", "expected_fragment"),
        [
            ("carbon_intensity", "", "CORTINA_1_N106", "zones"),
            ("carbon_intensity_forecast", "", None, "zones"),
            ("locational_marginal_price_day_ahead", "DE", " , ", "pricing nodes"),
        ],
    )
    def test_missing_zones_or_nodes_raises(
        self, endpoint: str, zones: str, pricing_nodes: str | None, expected_fragment: str
    ) -> None:
        result = _driver(zones=zones, pricing_nodes=pricing_nodes).run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert expected_fragment in str(result.raised)
        assert result.requests == []


class TestSnapshotEndpoints:
    def test_forecast_rows_carry_zone_and_issue_time_from_envelope(self) -> None:
        result = _driver("DE, SE").run(
            "carbon_intensity_forecast",
            [
                ScriptedResponse(
                    json={
                        "zone": "DE",
                        "updatedAt": "2025-06-15T11:00:00.000Z",
                        "forecast": [
                            {"carbonIntensity": 250, "datetime": "2025-06-15T12:00:00.000Z"},
                            {"carbonIntensity": 240, "datetime": "2025-06-15T13:00:00.000Z"},
                        ],
                    }
                ),
                ScriptedResponse(json={"zone": "SE", "updatedAt": "2025-06-15T11:00:00.000Z", "forecast": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v3/carbon-intensity/forecast", "/v3/carbon-intensity/forecast"]
        assert result.params("zone") == ["DE", "SE"]
        assert result.rows == [
            {
                "carbonIntensity": 250,
                "datetime": datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
                "zone": "DE",
                "updatedAt": datetime(2025, 6, 15, 11, 0, 0, tzinfo=UTC),
            },
            {
                "carbonIntensity": 240,
                "datetime": datetime(2025, 6, 15, 13, 0, 0, tzinfo=UTC),
                "zone": "DE",
                "updatedAt": datetime(2025, 6, 15, 11, 0, 0, tzinfo=UTC),
            },
        ]

    @pytest.mark.parametrize("body", [{"zone": "DE"}, {"zone": "DE", "forecast": None}])
    def test_forecast_response_without_forecast_list_fails_the_sync(self, body: dict[str, Any]) -> None:
        result = _driver().run("carbon_intensity_forecast", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "forecast list for zone DE" in str(result.raised)

    def test_zones_object_is_flattened_to_one_row_per_zone(self) -> None:
        result = _driver(zones="").run(
            "zones",
            [
                ScriptedResponse(
                    json={
                        "DK-DK2": {"zoneKey": "DK-DK2", "zoneName": "East Denmark", "zoneParentKey": "DK"},
                        "DE": {"zoneName": "Germany", "zoneParentKey": None},
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v3/zones"]
        assert result.rows == [
            {"zoneKey": "DK-DK2", "zoneName": "East Denmark", "zoneParentKey": "DK"},
            {"zoneKey": "DE", "zoneName": "Germany", "zoneParentKey": None},
        ]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_fragment"),
        [
            (404, False, "does not recognize zone DE"),
        ],
    )
    def test_status_maps_to_user_message(
        self, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("test-token", ["DE"])

        assert network.requests_log[0].param("zone") == "DE"
        assert is_valid is expected_valid
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message

    def test_stops_at_first_failing_zone(self) -> None:
        with scripted_network([ScriptedResponse(status=200), ScriptedResponse(status=403)]) as network:
            is_valid, message = validate_credentials("test-token", ["DE", "XX"])

        assert is_valid is False
        assert message is not None and "zone XX" in message
        assert [request.param("zone") for request in network.requests_log] == ["DE", "XX"]
