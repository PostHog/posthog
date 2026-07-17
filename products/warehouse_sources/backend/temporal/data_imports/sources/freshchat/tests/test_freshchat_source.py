from typing import Optional

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat import FreshchatResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source import FreshchatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshchatSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source.validate_freshchat_credentials"
)


def _make_inputs(schema_name: str = "agents") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestFreshchatSource:
    def setup_method(self) -> None:
        self.source = FreshchatSource()
        self.team_id = 1
        self.config = FreshchatSourceConfig(domain="acme.freshchat.com", api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FRESHCHAT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Freshchat"
        assert config.label == "Freshchat"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/freshchat"
        # A finished source is visible: the unreleased flag must never be re-added.
        assert not config.unreleasedSource

        fields = config.fields
        assert len(fields) == 2
        domain_field, api_key_field = fields
        assert isinstance(domain_field, SourceFieldInputConfig)
        assert domain_field.name == "domain"
        assert domain_field.type == SourceFieldInputConfigType.TEXT
        assert domain_field.secret is False
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs Supported-tables section can render.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields(self) -> None:
        # The domain is where the stored token is sent; editing it must re-require the secret.
        assert self.source.connection_host_fields == ["domain"]

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error", "403 Client Error: Forbidden for url", "Freshchat domain is not allowed"],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_covers_all_endpoints_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Freshchat has no server-side incremental cursor -> every endpoint is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    @pytest.mark.parametrize(
        "name, primary_keys",
        [
            ("agents", ["id"]),
            ("users", ["id"]),
            ("groups", ["id"]),
            ("channels", ["id"]),
            ("accounts_configuration", ["app_id"]),
        ],
    )
    def test_schema_primary_keys(self, name: str, primary_keys: list[str]) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].detected_primary_keys == primary_keys

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["agents"])
        assert len(schemas) == 1
        assert schemas[0].name == "agents"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "domain, status, schema_name, expected_valid, expect_probe",
        [
            ("acme.freshchat.com", 200, None, True, True),
            ("acme.freshchat.com", 403, None, True, True),  # missing scope at source-create is accepted
            ("acme.freshchat.com", 403, "agents", False, True),  # missing scope for a specific schema fails
            ("acme.freshchat.com", 401, None, False, True),
            ("acme.freshchat.com", None, None, False, True),  # connection error
            ("not a domain!", 200, None, False, False),  # domain regex rejects before probing
            # Non-Freshworks hosts are refused before probing — the stored token must never be
            # sent to a customer-chosen internal host (SSRF).
            ("metadata.google.internal", 200, None, False, False),
            ("api.default.svc.cluster.local", 200, None, False, False),
            ("evilfreshchat.com", 200, None, False, False),  # suffix match must not accept lookalikes
        ],
    )
    def test_validate_credentials(
        self,
        domain: str,
        status: Optional[int],
        schema_name: Optional[str],
        expected_valid: bool,
        expect_probe: bool,
    ) -> None:
        config = FreshchatSourceConfig(domain=domain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if not expect_probe:
            mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FreshchatResumeConfig

    def test_source_for_pipeline_plumbing(self) -> None:
        inputs = _make_inputs("agents")
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "agents"
        assert response.primary_keys == ["id"]
        # Full refresh, paged with an explicit ascending sort.
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
