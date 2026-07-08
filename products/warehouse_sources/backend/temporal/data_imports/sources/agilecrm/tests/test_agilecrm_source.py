from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm import source as agilecrm_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm import AgileCRMResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.source import AgileCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AgileCRMSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> AgileCRMSourceConfig:
    return AgileCRMSourceConfig(domain="acme", email="a@b.com", api_key="key")


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert AgileCRMSource().source_type == ExternalDataSourceType.AGILECRM

    def test_get_source_config_basics(self) -> None:
        config = AgileCRMSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.CRM
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/agilecrm"
        # Ships hidden behind unreleasedSource for now, labelled alpha.
        assert config.unreleasedSource is True

    def test_fields_are_domain_email_api_key(self) -> None:
        fields = AgileCRMSource().get_source_config.fields
        assert [f.name for f in fields] == ["domain", "email", "api_key"]
        by_name = {f.name: f for f in fields}
        api_key, domain, email = by_name["api_key"], by_name["domain"], by_name["email"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(domain, SourceFieldInputConfig)
        assert isinstance(email, SourceFieldInputConfig)
        assert api_key.secret is True
        assert domain.secret is False
        assert email.secret is False

    def test_domain_is_a_connection_host_field(self) -> None:
        # Retargeting the domain (where the API key is sent) must re-require secrets.
        assert AgileCRMSource().connection_host_fields == ["domain"]


class TestSchemas:
    def test_lists_all_endpoints_full_refresh_only(self) -> None:
        schemas = AgileCRMSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = AgileCRMSource().get_schemas(_config(), team_id=1, names=["contacts"])
        assert [s.name for s in schemas] == ["contacts"]

    def test_lists_tables_without_credentials(self) -> None:
        assert AgileCRMSource.lists_tables_without_credentials is True

    def test_documented_tables_render_from_static_catalog(self) -> None:
        tables = AgileCRMSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS).issubset(names)
        contacts = next(t for t in tables if t["name"] == "contacts")
        assert "Full refresh" in contacts["sync_methods"]
        # Canonical descriptions should flow through to the docs.
        assert contacts["description"]


class TestCanonicalDescriptions:
    def test_covers_known_endpoints(self) -> None:
        descriptions = AgileCRMSource().get_canonical_descriptions()
        assert "contacts" in descriptions
        assert descriptions["contacts"]["columns"]["id"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://acme.agilecrm.com/dev/api/contacts"),
            ("forbidden", "403 Client Error: Forbidden for url: https://acme.agilecrm.com/dev/api/opportunity"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = AgileCRMSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error"),
            ("timeout", "Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = AgileCRMSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: True)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: False)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None


class TestPipelinePlumbing:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        manager = AgileCRMSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AgileCRMResumeConfig

    def test_source_for_pipeline_passes_endpoint_and_primary_keys(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "contacts"
        response = AgileCRMSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert response.name == "contacts"
        assert response.primary_keys == ["id"]
