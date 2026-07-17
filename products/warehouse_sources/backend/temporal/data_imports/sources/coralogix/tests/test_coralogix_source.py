from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.coralogix import CoralogixResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source import CoralogixSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoralogixSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(
    api_key: str = "test-key", domain: str = "eu2.coralogix.com", tier: str = "frequent_search"
) -> CoralogixSourceConfig:
    return CoralogixSourceConfig.from_dict({"api_key": api_key, "domain": domain, "tier": tier})


def _inputs(schema_name: str, should_use_incremental_field: bool = False, last_value: Any = None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="timestamp" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestCoralogixSource:
    def test_source_type(self) -> None:
        assert CoralogixSource().source_type == ExternalDataSourceType.CORALOGIX

    def test_source_config_shape(self) -> None:
        config = CoralogixSource().get_source_config
        # A finished source must be visible: unreleasedSource hides the connector from every user.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/coralogix"
        assert [f.name for f in config.fields] == ["domain", "api_key", "tier"]
        api_key_field = config.fields[1]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True

    def test_domain_options_match_the_transport_allowlist(self) -> None:
        # The transport rejects domains outside CORALOGIX_DOMAINS, so an option added to the
        # form without extending the allowlist would break that region at sync time (and an
        # allowlist entry without an option would be unreachable).
        from products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.settings import (
            CORALOGIX_DOMAINS,
        )

        domain_field = CoralogixSource().get_source_config.fields[0]
        assert isinstance(domain_field, SourceFieldSelectConfig)
        assert {option.value for option in domain_field.options} == CORALOGIX_DOMAINS

    def test_domain_is_a_connection_host_field(self) -> None:
        # `domain` picks the cluster the stored API key is sent to, so retargeting it must force
        # the editor to re-enter the key.
        assert CoralogixSource().connection_host_fields == ["domain"]

    def test_get_schemas_are_append_only(self) -> None:
        # Logs and spans are immutable telemetry: append (timestamp watermark) is the only
        # incremental mode. Advertising merge-based incremental would re-merge huge immutable
        # tables for no benefit.
        schemas = CoralogixSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == {"logs", "spans"}
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is True
            assert [f["field"] for f in schema.incremental_fields] == ["timestamp"]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = CoralogixSource().get_schemas(_config(), team_id=1, names=["logs"])
        assert [s.name for s in schemas] == ["logs"]

    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate_credentials(self, _name: str, probe_result: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source.validate_coralogix_credentials",
            return_value=probe_result,
        ) as probe:
            valid, error = CoralogixSource().validate_credentials(_config("key-1", "coralogix.us"), team_id=1)

        probe.assert_called_once_with("key-1", "coralogix.us")
        assert valid is probe_result
        assert (error is None) is probe_result

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.eu2.coralogix.com/api/v1/dataprime/query",),
            ("403 Client Error: Forbidden for url: https://api.coralogix.us/api/v1/dataprime/query",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked key or wrong-cluster domain must permanently fail the sync rather than retry
        # forever; the matcher keys on the stable status text + URL prefix shared by every domain.
        errors = CoralogixSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = CoralogixSource().get_resumable_source_manager(_inputs("logs"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CoralogixResumeConfig

    @parameterized.expand([("incremental", True, "2026-01-01"), ("full_refresh", False, None)])
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, should_use_incremental_field: bool, expected_last_value: Any
    ) -> None:
        sentinel = object()
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coralogix.source.coralogix_source",
            return_value=sentinel,
        ) as mock_source:
            inputs = _inputs("spans", should_use_incremental_field, last_value="2026-01-01")
            result = CoralogixSource().source_for_pipeline(
                _config("key-123", "coralogix.in", "archive"), manager, inputs
            )

        assert result is sentinel
        mock_source.assert_called_once_with(
            api_key="key-123",
            domain="coralogix.in",
            tier="archive",
            endpoint="spans",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials=True` powers the public docs table catalog; it must
        # resolve from the static endpoint catalog with no network call and merge canonical
        # descriptions.
        tables = CoralogixSource().get_documented_tables()
        by_name: dict[str, dict[str, Any]] = {t["name"]: t for t in tables}
        assert set(by_name) == {"logs", "spans"}
        assert by_name["logs"]["sync_methods"] == ["Append only", "Full refresh"]
        assert by_name["logs"]["primary_keys"] == ["logid"]
        assert by_name["spans"]["description"]
