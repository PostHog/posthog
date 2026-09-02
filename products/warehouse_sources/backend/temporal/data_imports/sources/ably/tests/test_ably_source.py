import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.source import AblySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ably import AblySourceConfig


class TestAblySource:
    def setup_method(self):
        self.source = AblySource()
        self.team_id = 123

    def _field(self, name: str):
        return next(f for f in self.source.get_source_config.fields if f.name == name)

    def test_api_key_field_is_secret_password(self):
        field = self._field("api_key")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_unit_field_defaults_to_hour(self):
        field = self._field("unit")
        assert isinstance(field, SourceFieldSelectConfig)
        assert field.defaultValue == "hour"
        assert {option.value for option in field.options} == {"minute", "hour", "day", "month"}

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, None)),
            (401, (False, "Ably authentication failed. Please check your API key.")),
            (403, (False, "Ably authentication failed. Please check your API key.")),
        ],
    )
    def test_validate_credentials(self, status_code, expected):
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        mock_response = MagicMock(status_code=status_code)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = mock_response
            assert self.source.validate_credentials(config, self.team_id) == expected

    def test_validate_credentials_rejects_malformed_key(self):
        config = AblySourceConfig(api_key="no-colon-here", unit="hour")
        ok, error = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert error is not None and "malformed" in error.lower()

    def test_source_for_pipeline_plumbs_config_and_returns_expected_response_shape(self):
        config = AblySourceConfig(api_key="app.key:secret", unit="day")
        inputs = MagicMock(
            team_id=self.team_id,
            job_id="job-1",
            schema_name="Stats",
            api_version="2",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
        )
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.source.ably_source"
        ) as mock_ably_source:
            mock_resource = MagicMock(name="Stats", column_hints={"interval_start": "timestamp"})
            mock_resource.name = "Stats"
            mock_ably_source.return_value = mock_resource

            response = self.source.source_for_pipeline(config, manager, inputs)

            mock_ably_source.assert_called_once_with(
                api_key="app.key:secret",
                unit="day",
                team_id=self.team_id,
                job_id="job-1",
                resumable_source_manager=manager,
                api_version="2",
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000000,
            )

        assert response.name == "Stats"
        assert response.primary_keys == ["unit", "intervalId"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["interval_start"]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        ("pinned", "resolved"),
        [
            # No pin falls back to default_version ("2"); an explicit pin is honored verbatim,
            # including the legacy label so a deprecated source keeps its own request path.
            (None, "2"),
            ("v1", "v1"),
            ("2", "2"),
        ],
    )
    def test_source_for_pipeline_resolves_and_threads_api_version(self, pinned, resolved):
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        inputs = MagicMock(
            team_id=self.team_id,
            job_id="job-1",
            schema_name="Stats",
            api_version=pinned,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.source.ably_source"
        ) as mock_ably_source:
            mock_resource = MagicMock(column_hints=None)
            mock_resource.name = "Stats"
            mock_ably_source.return_value = mock_resource

            self.source.source_for_pipeline(config, manager, inputs)

            assert mock_ably_source.call_args.kwargs["api_version"] == resolved

    def test_source_for_pipeline_ignores_last_value_on_full_refresh(self):
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        inputs = MagicMock(
            team_id=self.team_id,
            job_id="job-1",
            schema_name="Stats",
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000000,
        )
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.source.ably_source"
        ) as mock_ably_source:
            mock_resource = MagicMock(name="Stats", column_hints=None)
            mock_resource.name = "Stats"
            mock_ably_source.return_value = mock_resource

            self.source.source_for_pipeline(config, manager, inputs)

            assert mock_ably_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize(
        "error_message",
        [
            "401 Client Error: Unauthorized for url: https://main.realtime.ably.net/stats",
            "403 Client Error: Forbidden for url: https://main.realtime.ably.net/stats",
        ],
    )
    def test_non_retryable_errors(self, error_message):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in non_retryable)
