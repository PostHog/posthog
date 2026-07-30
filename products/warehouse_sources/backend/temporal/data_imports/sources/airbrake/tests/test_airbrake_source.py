from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.airbrake import AirbrakeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source import AirbrakeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAirbrakeSource:
    def test_source_type(self) -> None:
        assert AirbrakeSource().source_type == ExternalDataSourceType.AIRBRAKE

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

    def test_get_schemas_returns_static_catalog(self) -> None:
        schemas = {s.name: s for s in AirbrakeSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"projects", "groups", "deploys", "notices"}

        # groups is the only endpoint with a server-side time filter (start_time on createdAt).
        assert schemas["groups"].supports_incremental is True
        assert [f["field"] for f in schemas["groups"].incremental_fields] == ["createdAt"]
        for full_refresh_only in ("projects", "deploys", "notices"):
            assert schemas[full_refresh_only].supports_incremental is False, full_refresh_only
            assert schemas[full_refresh_only].incremental_fields == []

        # notices is the API-expensive two-level fan-out and must stay opt-in.
        assert schemas["notices"].should_sync_default is False
        assert schemas["projects"].should_sync_default is True

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = AirbrakeSource().get_schemas(MagicMock(), team_id=1, names=["groups"])
        assert [s.name for s in schemas] == ["groups"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Airbrake user API key"))])
    def test_validate_credentials(self, _name: str, transport_result: bool, expected: tuple) -> None:
        config = MagicMock()
        config.api_key = "user-key"
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source.validate_airbrake_credentials",
            return_value=transport_result,
        ) as validate:
            assert AirbrakeSource().validate_credentials(config, team_id=1) == expected
        validate.assert_called_once_with("user-key")

    def test_resumable_source_manager_is_bound_to_airbrake_resume_config(self) -> None:
        inputs = MagicMock()
        manager = AirbrakeSource().get_resumable_source_manager(inputs)
        assert manager._data_class is AirbrakeResumeConfig

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
        config = MagicMock()
        config.api_key = "user-key"
        inputs = MagicMock()
        inputs.schema_name = "groups"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = last_value
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source.airbrake_source"
        ) as airbrake_source_mock:
            AirbrakeSource().source_for_pipeline(config, manager, inputs)

        airbrake_source_mock.assert_called_once_with(
            api_key="user-key",
            endpoint="groups",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.airbrake.io/api/v4/projects?key=x"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.airbrake.io/api/v4/projects/1/groups"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = AirbrakeSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.airbrake.io', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.airbrake.io/api/v4/projects",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = AirbrakeSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable_errors)
