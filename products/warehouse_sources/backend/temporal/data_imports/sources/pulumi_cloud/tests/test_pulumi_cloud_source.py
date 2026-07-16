from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PulumiCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.pulumi_cloud import (
    PulumiCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.source import PulumiCloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(
    schema_name: str, last_value: Optional[object] = None, use_incremental: bool = False
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=use_incremental,
        db_incremental_field_last_value=last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="timestamp" if use_incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestPulumiCloudSource:
    def setup_method(self) -> None:
        self.source = PulumiCloudSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PULUMICLOUD

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["access_token", "organization"]
        token_field, org_field = config.fields
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True
        assert isinstance(org_field, SourceFieldInputConfig)
        assert org_field.required is True
        assert org_field.secret is False

    def test_source_is_released_as_alpha(self) -> None:
        # unreleasedSource hides the connector from every user; a finished source must ship visible
        # with a soft ALPHA label instead.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/pulumi-cloud"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["stacks"])
        assert [s.name for s in schemas] == ["stacks"]

    @parameterized.expand(
        [
            # audit_logs has a server-side startTime lower bound; stack_updates pages newest-first
            # and stops client-side at the watermark. The snapshot/index endpoints are full refresh.
            ("stacks", False, [], True),
            ("stack_updates", True, ["startTime"], True),
            ("deployments", False, [], True),
            ("audit_logs", True, ["timestamp"], False),
            ("resources", False, [], True),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, incremental_fields: list[str], sync_default: bool
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Incremental runs re-pull an overlap window that merge dedupes; append would duplicate it.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields
        # audit_logs is tier-gated in Pulumi Cloud; defaulting it on would fail most first syncs.
        assert schema.should_sync_default is sync_default

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        config = PulumiCloudSourceConfig(access_token="pul-test", organization="my-org")
        with patch.object(source_module, "validate_pulumi_cloud_credentials", return_value=probe_result):
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.pulumi.com/api/user/stacks"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.pulumi.com/api/orgs/my-org/auditlogs/v2"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("stacks"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PulumiCloudResumeConfig

    def test_source_for_pipeline_plumbs_credentials_and_endpoint(self) -> None:
        config = PulumiCloudSourceConfig(access_token="pul-test", organization="my-org")
        inputs = _source_inputs("audit_logs", last_value=1750000000, use_incremental=True)
        with patch.object(source_module, "pulumi_cloud_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "pul-test"
        assert kwargs["organization"] == "my-org"
        assert kwargs["endpoint"] == "audit_logs"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1750000000

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        # Passing a stale watermark on a full-refresh run would wrongly narrow the audit-log window.
        config = PulumiCloudSourceConfig(access_token="pul-test", organization="my-org")
        inputs = _source_inputs("audit_logs", last_value=1750000000, use_incremental=False)
        with patch.object(source_module, "pulumi_cloud_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Drift here (an endpoint renamed in settings but not here) silently drops the curated docs
        # and falls back to LLM enrichment, so keep the two in lockstep.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
