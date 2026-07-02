from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailerSendSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.mailersend import (
    MailerSendResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.source import MailerSendSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MailerSendSourceConfig:
    return MailerSendSourceConfig.from_dict({"api_token": "mlsn.token"})


class TestMailerSendSourceConfig:
    def test_source_type(self) -> None:
        assert MailerSendSource().source_type == ExternalDataSourceType.MAILERSEND

    def test_source_config_metadata(self) -> None:
        config = MailerSendSource().get_source_config
        assert config.label == "MailerSend"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        # Stays hidden behind the unreleased flag while in alpha.
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_single_secret_api_token_field(self) -> None:
        fields = MailerSendSource().get_source_config.fields
        assert [f.name for f in fields] == ["api_token"]
        api_token = fields[0]
        assert isinstance(api_token, SourceFieldInputConfig)
        assert api_token.required is True
        assert api_token.secret is True


class TestGetSchemas:
    def test_exposes_every_endpoint(self) -> None:
        names = {s.name for s in MailerSendSource().get_schemas(_config(), team_id=1)}
        assert names == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("domains", False, False),
            ("recipients", False, False),
            ("templates", False, False),
            ("messages", False, False),
            ("activity", True, True),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, supports_append: bool
    ) -> None:
        schemas = {s.name: s for s in MailerSendSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports_incremental
        assert schemas[endpoint].supports_append is supports_append

    def test_only_activity_is_incremental(self) -> None:
        # Only the Activity endpoint exposes a server-side date filter; the rest are full refresh.
        schemas = {s.name: s for s in MailerSendSource().get_schemas(_config(), team_id=1)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"activity"}

    def test_names_filter(self) -> None:
        schemas = MailerSendSource().get_schemas(_config(), team_id=1, names=["domains"])
        assert [s.name for s in schemas] == ["domains"]


class TestValidateCredentials:
    def test_delegates_to_check_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "check_credentials", lambda token, schema: (True, None))
        ok, error = MailerSendSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_passes_schema_name_through(self, monkeypatch: Any) -> None:
        seen: dict[str, Any] = {}

        def fake_check(token: str, schema: str | None) -> tuple[bool, str | None]:
            seen["token"] = token
            seen["schema"] = schema
            return False, "bad"

        monkeypatch.setattr(source_module, "check_credentials", fake_check)
        ok, error = MailerSendSource().validate_credentials(_config(), team_id=1, schema_name="activity")
        assert ok is False
        assert seen == {"token": "mlsn.token", "schema": "activity"}


class TestNonRetryableErrors:
    @parameterized.expand(["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    def test_auth_errors_are_non_retryable(self, status_text: str) -> None:
        error = f"{status_text} for url: https://api.mailersend.com/v1/domains?page=1"
        non_retryable = MailerSendSource().get_non_retryable_errors()
        assert any(key in error for key in non_retryable)

    @parameterized.expand(
        [
            "500 Server Error: Internal Server Error for url: https://api.mailersend.com/v1/domains",
            "HTTPSConnectionPool(host='api.mailersend.com', port=443): Read timed out.",
        ]
    )
    def test_transient_errors_remain_retryable(self, error: str) -> None:
        non_retryable = MailerSendSource().get_non_retryable_errors()
        assert not any(key in error for key in non_retryable)


class TestResumableWiring:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = MailerSendSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MailerSendResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(source_module, "mailersend_source", fake_source)

        inputs = MagicMock()
        inputs.schema_name = "activity"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        manager = MagicMock()

        MailerSendSource().source_for_pipeline(_config(), manager, inputs)

        assert captured["api_token"] == "mlsn.token"
        assert captured["endpoint"] == "activity"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "mailersend_source", lambda **kw: captured.update(kw))

        inputs = MagicMock()
        inputs.schema_name = "domains"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        MailerSendSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None


class TestCanonicalDescriptions:
    def test_covers_every_endpoint(self) -> None:
        descriptions = MailerSendSource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_activity_documents_injected_domain_id(self) -> None:
        # domain_id is added by PostHog, not MailerSend, so it must be documented for the AI agent.
        activity = MailerSendSource().get_canonical_descriptions()["activity"]
        assert "domain_id" in activity["columns"]
