from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OnePasswordSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword import (
    OnePasswordResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.source import OnePasswordSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_FEATURES_INTROSPECTION = {
    "uuid": "OK41XEGLRTH4YKO5YRTCPNX3IU",
    "features": ["auditevents", "itemusages", "signinattempts"],
}


def _source_inputs(schema_name: str, last_value: Optional[Any] = None, use_incremental: bool = False) -> SourceInputs:
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


class TestOnePasswordSource:
    def setup_method(self) -> None:
        self.source = OnePasswordSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ONEPASSWORD

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        assert len(config.fields) == 2
        region, token = config.fields
        assert isinstance(region, SourceFieldSelectConfig)
        assert region.name == "region"
        assert [option.value for option in region.options] == ["us", "ca", "eu", "enterprise"]
        assert isinstance(token, SourceFieldInputConfig)
        assert token.name == "api_token"
        assert token.type == SourceFieldInputConfigType.PASSWORD
        assert token.required is True
        assert token.secret is True

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/onepassword"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs table list must render.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["audit_events"])
        assert [s.name for s in schemas] == ["audit_events"]

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_stream_is_incremental_merge_only(self, endpoint: str) -> None:
        # `start_time` is a genuine server-side filter on every stream; append is never offered
        # because incremental runs re-pull a boundary window that only merge dedupes on `uuid`.
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["timestamp"]

    @parameterized.expand(
        [
            ("valid_token", ALL_FEATURES_INTROSPECTION, None, True),
            ("invalid_token", None, None, False),
            ("scoped_schema_with_feature", ALL_FEATURES_INTROSPECTION, "audit_events", True),
            ("scoped_schema_missing_feature", {"features": ["itemusages"]}, "audit_events", False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, introspection: dict | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value=introspection):
            ok, error = self.source.validate_credentials(config, team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_endpoint_permissions_report_missing_features(self) -> None:
        # A token scoped to a subset of features must surface which tables it can't read so the
        # schema picker can flag them — without blocking the reachable ones.
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value={"features": ["signinattempts"]}):
            permissions = self.source.get_endpoint_permissions(config, team_id=1, endpoints=list(ENDPOINTS))
        assert permissions["sign_in_attempts"] is None
        assert permissions["item_usages"] is not None
        assert permissions["audit_events"] is not None

    def test_endpoint_permissions_never_block_on_probe_failure(self) -> None:
        config = OnePasswordSourceConfig(api_token="token", region="us")
        with patch.object(source_module, "introspect", return_value=None):
            permissions = self.source.get_endpoint_permissions(config, team_id=1, endpoints=list(ENDPOINTS))
        assert all(reason is None for reason in permissions.values())

    @parameterized.expand(
        [
            ("us", "401 Client Error: Unauthorized for url: https://events.1password.com/api/v2/auditevents"),
            ("eu", "401 Client Error: Unauthorized for url: https://events.1password.eu/api/v2/itemusages"),
            (
                "enterprise",
                "401 Client Error: Unauthorized for url: https://events.ent.1password.com/api/v2/signinattempts",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable_for_every_region(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("audit_events"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OnePasswordResumeConfig

    def test_source_for_pipeline_plumbs_config_and_endpoint(self) -> None:
        config = OnePasswordSourceConfig(api_token="token", region="eu")
        inputs = _source_inputs("audit_events", last_value="2026-07-01T00:00:00Z", use_incremental=True)
        with patch.object(source_module, "onepassword_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "audit_events"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-01T00:00:00Z"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        # A stale watermark on a full-refresh run would wrongly narrow the start_time window.
        config = OnePasswordSourceConfig(api_token="token", region="us")
        inputs = _source_inputs("audit_events", last_value="2026-07-01T00:00:00Z", use_incremental=False)
        with patch.object(source_module, "onepassword_source") as mock_source:
            self.source.source_for_pipeline(config, MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Drift here (an endpoint renamed in settings but not here) silently drops the curated docs
        # and falls back to LLM enrichment, so keep the two in lockstep.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
