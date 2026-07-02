from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.source import ZendeskSellSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell import (
    ZendeskSellResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert ZendeskSellSource().source_type == ExternalDataSourceType.ZENDESKSELL

    def test_config_is_crm_alpha_and_unreleased(self) -> None:
        config = ZendeskSellSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.CRM
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Alpha ships hidden until end-to-end sync is verified against a live account.
        assert config.unreleasedSource is True

    def test_config_exposes_single_password_access_token_field(self) -> None:
        fields = ZendeskSellSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "access_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True


class TestGetSchemas:
    def test_every_endpoint_is_full_refresh(self) -> None:
        schemas = ZendeskSellSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = ZendeskSellSource().get_schemas(MagicMock(), team_id=1, names=["deals", "leads"])
        assert {s.name for s in schemas} == {"deals", "leads"}


class TestValidateCredentials:
    @parameterized.expand(
        [("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zendesk Sell access token"))]
    )
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        config = MagicMock(access_token="token")
        with patch.object(source_module, "validate_zendesk_sell_credentials", return_value=probe_result):
            assert ZendeskSellSource().validate_credentials(config, team_id=1) == expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.getbase.com/v2/contacts?per_page=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getbase.com/v2/deals?per_page=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = ZendeskSellSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.getbase.com/v2/contacts"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.getbase.com/v2/deals"),
            ("read_timeout", "HTTPSConnectionPool(host='api.getbase.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = ZendeskSellSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableManager:
    def test_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = ZendeskSellSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZendeskSellResumeConfig


class TestSourceForPipeline:
    def test_plumbs_config_and_inputs_into_source_response(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = SourceResponse(name="deals", items=lambda: iter(()), primary_keys=["id"])

        def fake_source(**kwargs: Any) -> SourceResponse:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "zendesk_sell_source", fake_source)

        config = MagicMock(access_token="my-token")
        manager = MagicMock()
        inputs = MagicMock(schema_name="deals")
        inputs.logger = MagicMock()

        result = ZendeskSellSource().source_for_pipeline(config, manager, inputs)

        assert result is sentinel
        assert captured["access_token"] == "my-token"
        assert captured["endpoint"] == "deals"
        assert captured["resumable_source_manager"] is manager


class TestCanonicalDescriptions:
    def test_descriptions_key_off_known_endpoints(self) -> None:
        descriptions = ZendeskSellSource().get_canonical_descriptions()
        assert descriptions  # non-empty
        # Every documented entry must map to a real endpoint name so enrichment lands on the table.
        assert set(descriptions).issubset(set(ENDPOINTS))
        for entry in descriptions.values():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://")
