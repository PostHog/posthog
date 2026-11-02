from datetime import UTC, datetime

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source import AirbrakeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airbrake import (
    AirbrakeSourceConfig,
)


class TestAirbrakeSource:
    def test_source_is_visible_with_secret_api_key_field(self) -> None:
        config = AirbrakeSource().get_source_config
        # Re-adding unreleasedSource would silently hide the connector from every user.
        assert not config.unreleasedSource

        assert config.fields is not None
        field_by_name = {f.name: f for f in config.fields}
        api_key = field_by_name["api_key"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Airbrake user API key"))])
    def test_validate_credentials(self, _name: str, transport_result: bool, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=200 if transport_result else 401)]) as network:
            result = AirbrakeSource().validate_credentials(AirbrakeSourceConfig(api_key="user-key"), team_id=1)
            assert result == expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].param("key") == "user-key"

    @parameterized.expand(
        [
            # The watermark must not leak into a full-refresh run: a stale value would silently
            # turn the refresh into a partial sync.
            ("incremental", True, datetime(2026, 3, 4, tzinfo=UTC), datetime(2026, 3, 4, tzinfo=UTC)),
            ("full_refresh_drops_stale_watermark", False, datetime(2026, 3, 4, tzinfo=UTC), None),
        ]
    )
    def test_source_for_pipeline_plumbs_incremental_inputs(
        self, _name: str, should_use_incremental_field: bool, last_value: datetime, expected_last_value: datetime | None
    ) -> None:
        result = SourceDriver(AirbrakeSource(), AirbrakeSourceConfig(api_key="user-key")).run(
            "groups",
            [
                ScriptedResponse(json={"count": 1, "projects": [{"id": 1}]}),
                ScriptedResponse(json={"count": 1, "groups": [{"id": "g1"}]}),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.rows == [{"id": "g1"}]
        assert result.paths == ["/api/v4/projects", "/api/v4/projects/1/groups"]
        assert result.requests[1].param("key") == "user-key"
        assert result.requests[1].param("start_time") == (
            "2026-03-04T00:00:00.000Z" if expected_last_value is not None else None
        )
