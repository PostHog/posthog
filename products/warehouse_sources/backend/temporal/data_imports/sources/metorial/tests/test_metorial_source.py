from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetorialSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import MetorialResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source import MetorialSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source"


def _config() -> MetorialSourceConfig:
    return MetorialSourceConfig.from_dict({"api_key": "metorial_sk_test"})


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert MetorialSource().source_type.value == "Metorial"

    def test_api_key_is_a_required_secret_field(self) -> None:
        # A non-secret key field would be stored unencrypted; a non-required one would let a source be
        # created with no credentials.
        fields = MetorialSource().get_source_config.fields
        api_key = next(f for f in fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True


class TestSchemas:
    @parameterized.expand(
        [
            # Mutable resources (carry updated_at) must merge, never append — append duplicates a row
            # every time its status/usage changes.
            ("sessions", True, False),
            ("provider_runs", True, False),
            ("provider_deployments", True, False),
            # tool_calls mutate status but expose no updated_at, so incremental-merge on created_at.
            ("tool_calls", True, False),
            # Immutable event streams keyed on created_at: append is safe.
            ("session_messages", True, True),
            ("session_errors", True, True),
            # No server-side timestamp filter: full refresh only.
            ("providers", False, False),
        ]
    )
    def test_incremental_and_append_support(self, endpoint: str, incremental: bool, append: bool) -> None:
        schemas = {s.name: s for s in MetorialSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append

    def test_providers_is_off_by_default(self) -> None:
        # providers is a global catalog, not project data — syncing it every time by default would
        # burn the tight rate limit for little value.
        schemas = {s.name: s for s in MetorialSource().get_schemas(_config(), team_id=1)}
        assert schemas["providers"].should_sync_default is False

    def test_names_filter(self) -> None:
        schemas = MetorialSource().get_schemas(_config(), team_id=1, names=["sessions"])
        assert [s.name for s in schemas] == ["sessions"]

    def test_lists_documented_tables_without_credentials(self) -> None:
        # The static catalog powers the public docs "Supported tables" section.
        source = MetorialSource()
        assert source.lists_tables_without_credentials is True
        assert {t["name"] for t in source.get_documented_tables()} == {
            s.name for s in source.get_schemas(_config(), team_id=1)
        }


class TestValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_maps_probe_result(self, _name: str, probe_ok: bool) -> None:
        with patch(f"{_SOURCE_MODULE}.validate_metorial_credentials", return_value=probe_ok):
            ok, error = MetorialSource().validate_credentials(_config(), team_id=1)
        assert ok is probe_ok
        assert (error is None) is probe_ok


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.metorial.com/sessions?limit=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.metorial.com/provider-runs"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        keys = MetorialSource().get_non_retryable_errors()
        assert any(key in observed for key in keys)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.metorial.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.metorial.com/sessions"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.metorial.com/tool-calls"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        keys = MetorialSource().get_non_retryable_errors()
        assert not any(key in observed for key in keys)


class TestSourceForPipeline:
    def test_threads_incremental_inputs_into_transport(self) -> None:
        # Guards the wiring: the user's chosen endpoint, cursor field, and watermark must reach the
        # transport, and the watermark must be suppressed when incremental sync is off.
        inputs = SourceInputs(
            schema_name="sessions",
            schema_id="sid",
            source_id="src",
            team_id=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-04T00:00:00.000Z",
            db_incremental_field_earliest_value=None,
            incremental_field="updated_at",
            incremental_field_type=None,
            job_id="job",
            logger=MagicMock(),
            reset_pipeline=False,
        )
        manager = MagicMock()
        with patch(f"{_SOURCE_MODULE}.metorial_source") as mock_source:
            MetorialSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "metorial_sk_test"
        assert kwargs["endpoint"] == "sessions"
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-03-04T00:00:00.000Z"

    def test_suppresses_watermark_when_not_incremental(self) -> None:
        inputs = SourceInputs(
            schema_name="providers",
            schema_id="sid",
            source_id="src",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value="should-be-ignored",
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="job",
            logger=MagicMock(),
            reset_pipeline=False,
        )
        with patch(f"{_SOURCE_MODULE}.metorial_source") as mock_source:
            MetorialSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestResumableManager:
    def test_manager_is_bound_to_resume_config(self) -> None:
        inputs: Any = MagicMock()
        manager = MetorialSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MetorialResumeConfig
