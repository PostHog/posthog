from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ScalewaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.scaleway import ScalewayResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.source import ScalewaySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> ScalewaySourceConfig:
    return ScalewaySourceConfig(secret_key="scw-secret", organization_id="org-123")


class TestScalewaySource:
    def setup_method(self) -> None:
        self.source = ScalewaySource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SCALEWAY

    def test_secret_key_field_is_marked_secret(self) -> None:
        # A secret leaking as a plain (non-secret) field would be stored/echoed in cleartext, so lock
        # this down: secret_key must be a secret PASSWORD field; organization_id is a plain identifier.
        fields = {f.name: f for f in self.source.get_source_config.fields}
        secret_key_field = fields["secret_key"]
        organization_id_field = fields["organization_id"]
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert isinstance(organization_id_field, SourceFieldInputConfig)
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.secret is True
        assert organization_id_field.secret is not True

    def test_ships_as_alpha_and_unreleased(self) -> None:
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/scaleway"

    @parameterized.expand([("unauthorized", "401"), ("forbidden", "403")])
    def test_auth_errors_are_non_retryable(self, _name: str, status: str) -> None:
        assert any(status in key for key in self.source.get_non_retryable_errors())

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_every_schema_is_full_refresh_only(self, endpoint: str) -> None:
        # No endpoint has a verified server-side "updated since" filter, so none may advertise
        # incremental/append — otherwise the picker offers a mode that would sync nothing new.
        schemas = {s.name: s for s in self.source.get_schemas(_config(), self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_api_keys_primary_key_is_access_key(self) -> None:
        # API keys have no `id`; keying on the wrong column seeds duplicate rows that every merge
        # multi-matches.
        schemas = {s.name: s for s in self.source.get_schemas(_config(), self.team_id)}
        assert schemas["api_keys"].detected_primary_keys == ["access_key"]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(_config(), self.team_id, names=["invoices", "users"])
        assert {s.name for s in schemas} == {"invoices", "users"}

    @parameterized.expand(
        [
            # (probe status, schema_name, expected valid)
            ("create_ok", 200, None, True),
            ("create_missing_scope_accepted", 403, None, True),
            ("create_bad_token", 401, None, False),
            ("schema_ok", 200, "invoices", True),
            ("schema_missing_scope_rejected", 403, "invoices", False),
            ("schema_bad_token", 401, "invoices", False),
        ]
    )
    def test_validate_credentials(self, _name: str, status: int, schema_name: str | None, expected: bool) -> None:
        with (
            patch.object(source_module, "validate_scaleway_credentials", return_value=status),
            patch.object(source_module, "probe_endpoint", return_value=status),
        ):
            valid, _message = self.source.validate_credentials(_config(), self.team_id, schema_name=schema_name)
        assert valid is expected

    def test_validate_credentials_requires_organization_id(self) -> None:
        valid, message = self.source.validate_credentials(
            ScalewaySourceConfig(secret_key="scw-secret", organization_id=""), self.team_id
        )
        assert valid is False
        assert "Organization ID" in (message or "")

    @parameterized.expand([("forbidden", 403, True), ("reachable", 200, False), ("throttled", 429, False)])
    def test_endpoint_permissions_only_flags_real_denials(self, _name: str, status: int, is_blocked: bool) -> None:
        # Only a genuine 403 marks a table as needing extra scopes; a throttle or 5xx must not block
        # the picker (get_endpoint_permissions must never fail source creation for a transient blip).
        with patch.object(source_module, "probe_endpoint", return_value=status):
            result = self.source.get_endpoint_permissions(_config(), self.team_id, ["invoices"])
        assert (result["invoices"] is not None) is is_blocked

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = self._source_inputs("users")
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is ScalewayResumeConfig

    def test_source_for_pipeline_plumbs_endpoint(self) -> None:
        inputs = self._source_inputs("api_keys")
        response = self.source.source_for_pipeline(_config(), MagicMock(), inputs)
        assert response.name == "api_keys"
        assert response.primary_keys == ["access_key"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def _source_inputs(self, schema_name: str) -> SourceInputs:
        return SourceInputs(
            schema_name=schema_name,
            schema_id="schema-1",
            source_id="source-1",
            team_id=self.team_id,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="job-1",
            logger=MagicMock(),
            reset_pipeline=False,
        )
