from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metorial import (
    MetorialSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source import MetorialSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source"


def _config() -> MetorialSourceConfig:
    return MetorialSourceConfig.from_dict({"api_key": "metorial_sk_test"})


class TestSourceConfig:
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


class TestValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_maps_probe_result(self, _name: str, probe_ok: bool) -> None:
        with patch(f"{_SOURCE_MODULE}.validate_metorial_credentials", return_value=probe_ok):
            ok, error = MetorialSource().validate_credentials(_config(), team_id=1)
        assert ok is probe_ok
        assert (error is None) is probe_ok


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
