from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source import ElevenLabsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestElevenLabsSourceConfig:
    def test_source_type(self) -> None:
        assert ElevenLabsSource().source_type == ExternalDataSourceType.ELEVENLABS

    def test_config_exposes_api_key_password_field(self) -> None:
        config = ElevenLabsSource().get_source_config
        fields = {f.name: f for f in config.fields}
        assert "api_key" in fields
        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == "password"
        assert api_key_field.required is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/elevenlabs"


class TestElevenLabsSchemas:
    @parameterized.expand(
        [
            # history/conversations have real server-side time filters; agents/voices do not.
            ("history", True, True),
            ("conversations", True, False),
            ("agents", False, False),
            ("voices", False, False),
        ]
    )
    def test_schema_sync_capabilities(self, endpoint: str, incremental: bool, append: bool) -> None:
        # Marking conversations appendable would materialize post-call mutations (status/summary) as
        # duplicate rows; marking agents/voices incremental would break sync (no filter to honor).
        schemas = {s.name: s for s in ElevenLabsSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append

    def test_incremental_fields_are_unix_integers(self) -> None:
        schemas = {s.name: s for s in ElevenLabsSource().get_schemas(MagicMock(), team_id=1)}
        history = schemas["history"]
        assert [f["field"] for f in history.incremental_fields] == ["date_unix"]

    def test_names_filter_limits_returned_schemas(self) -> None:
        schemas = ElevenLabsSource().get_schemas(MagicMock(), team_id=1, names=["voices"])
        assert [s.name for s in schemas] == ["voices"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials must stay on so the posthog.com Supported tables section renders.
        tables = ElevenLabsSource().get_documented_tables()
        assert {t["name"] for t in tables} == {"history", "conversations", "agents", "voices"}


class TestElevenLabsNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.elevenlabs.io/v1/history"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.elevenlabs.io/v1/convai/conversations"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = ElevenLabsSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.elevenlabs.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.elevenlabs.io/v1/history"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        errors = ElevenLabsSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestElevenLabsPipelinePlumbing:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = ElevenLabsSource().get_resumable_source_manager(inputs)
        assert manager._data_class is ElevenLabsResumeConfig

    def test_source_for_pipeline_forwards_incremental_inputs(self) -> None:
        config = MagicMock(api_key="sk_test")
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="history",
            team_id=7,
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="date_unix",
        )
        with patch.object(source_module, "elevenlabs_source") as mocked:
            ElevenLabsSource().source_for_pipeline(config, manager, inputs)

        _args, kwargs = mocked.call_args
        assert kwargs["endpoint"] == "history"
        assert kwargs["api_key"] == "sk_test"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "date_unix"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # When incremental is off, the stored watermark must not leak into the request as a filter.
        inputs = MagicMock(
            schema_name="agents",
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
            incremental_field=None,
        )
        with patch.object(source_module, "elevenlabs_source") as mocked:
            ElevenLabsSource().source_for_pipeline(MagicMock(api_key="sk_test"), MagicMock(), inputs)

        _args, kwargs = mocked.call_args
        assert kwargs["db_incremental_field_last_value"] is None


def test_validate_credentials_delegates_to_transport() -> None:
    with patch.object(source_module, "validate_elevenlabs_credentials", return_value=(True, None)) as mocked:
        result = ElevenLabsSource().validate_credentials(MagicMock(api_key="sk_test"), team_id=1, schema_name="history")
    assert result == (True, None)
    assert mocked.call_args[0] == ("sk_test", "history")
