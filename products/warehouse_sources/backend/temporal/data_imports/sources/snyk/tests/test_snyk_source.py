from typing import Any, Optional

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnykSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.settings import (
    ENDPOINTS,
    SNYK_ENDPOINTS,
    SnykScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk import SnykResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source import SnykSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(
    schema_name: str = "issues",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestSnykSource:
    def setup_method(self) -> None:
        self.source = SnykSource()
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SNYK

    def test_credential_retargeting_fields_force_token_reentry(self) -> None:
        # `region` picks the host the token is sent to and `organization_id` picks the tenant it
        # reads; dropping either from this list would let an editor retarget the preserved token
        # without re-entering it.
        assert self.source.connection_host_fields == ["region", "organization_id"]

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Snyk"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token", "region", "organization_id"]

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.required is True
        assert token_field.secret is True

        region_field = config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert [o.value for o in region_field.options] == ["us", "eu", "au"]

        org_field = config.fields[2]
        assert isinstance(org_field, SourceFieldInputConfig)
        assert org_field.required is False

    def test_generated_config_parses_fields(self) -> None:
        # Guards the generated-config round trip: form fields must map to config attributes.
        config = SnykSourceConfig.from_dict({"api_token": "tok_123"})
        assert config.api_token == "tok_123"
        assert config.region == "us"
        assert config.organization_id is None

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("organizations", False),
            ("projects", False),
            ("targets", False),
            ("issues", True),
        ]
    )
    def test_only_issues_advertises_incremental(self, endpoint: str, expected: bool) -> None:
        # Issues is the only endpoint with a documented server-side timestamp filter
        # (updated_after / created_after); the others must stay full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["issues", "projects"])
        assert {s.name for s in schemas} == {"issues", "projects"}

    def test_publishes_table_catalog_for_public_docs(self) -> None:
        # `lists_tables_without_credentials` gates whether the static endpoint catalog reaches the
        # posthog.com "Supported tables" section; dropping it would silently empty that section.
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS).issubset(names)
        issues = next(t for t in tables if t["name"] == "issues")
        assert "Incremental" in issues["sync_methods"]
        assert issues["description"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source.validate_snyk_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = SnykSourceConfig.from_dict({"api_token": "tok", "region": "eu", "organization_id": "org-1"})
        ok, error = self.source.validate_credentials(config, self.team_id)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("eu", "tok", "org-1")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source.validate_snyk_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Snyk API token")
        ok, error = self.source.validate_credentials(SnykSourceConfig.from_dict({"api_token": "bad"}), self.team_id)
        assert ok is False
        assert error == "Invalid Snyk API token"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SnykResumeConfig

    @parameterized.expand(
        [
            ("organizations", ["id"]),
            ("projects", ["id", "organization_id"]),
            ("targets", ["id", "organization_id"]),
            ("issues", ["id", "organization_id"]),
        ]
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs(endpoint))
        response = self.source.source_for_pipeline(
            SnykSourceConfig.from_dict({"api_token": "tok"}), manager, _source_inputs(endpoint)
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_source_response_defers_watermark_to_completion(self) -> None:
        # Snyk offers no sort param and fan-out breaks global ordering, so the watermark must only
        # advance at sync completion ("desc" semantics) — "asc" would checkpoint mid-sync and skip
        # rows on retry.
        manager = self.source.get_resumable_source_manager(_source_inputs("issues"))
        response = self.source.source_for_pipeline(
            SnykSourceConfig.from_dict({"api_token": "tok"}), manager, _source_inputs("issues")
        )
        assert response.sort_mode == "desc"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source.snyk_source")
    def test_incremental_value_only_passed_when_enabled(self, mock_snyk_source: MagicMock) -> None:
        config = SnykSourceConfig.from_dict({"api_token": "tok"})
        manager = MagicMock()
        inputs = _source_inputs(
            "issues",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01",
            incremental_field="updated_at",
        )
        self.source.source_for_pipeline(config, manager, inputs)
        assert mock_snyk_source.call_args.kwargs["db_incremental_field_last_value"] is None

        inputs = _source_inputs(
            "issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01",
            incremental_field="updated_at",
        )
        self.source.source_for_pipeline(config, manager, inputs)
        assert mock_snyk_source.call_args.kwargs["db_incremental_field_last_value"] == "2026-01-01"
        assert mock_snyk_source.call_args.kwargs["incremental_field"] == "updated_at"

    def test_fan_out_children_carry_organization_id_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every org, so the injected org id must be part of
        # the primary key — otherwise per-org id collisions would seed duplicate rows that slow
        # every subsequent merge.
        for config in SNYK_ENDPOINTS.values():
            if config.scope is SnykScope.PER_ORG:
                assert "organization_id" in config.primary_keys, config.name

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.snyk.io/rest/orgs?version=2024-10-15",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.eu.snyk.io/rest/orgs/o1/issues?version=2024-10-15",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.snyk.io/rest/orgs"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.snyk.io/rest/orgs"),
            ("read_timeout", "HTTPSConnectionPool(host='api.snyk.io', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # Canonical descriptions are keyed by schema name; a typo'd key would silently never apply.
        descriptions: dict[str, Any] = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for entry in descriptions.values():
            assert entry["description"]
