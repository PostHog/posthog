import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailerLiteSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    MailerLiteResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source import MailerLiteSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MailerLiteSourceConfig:
    return MailerLiteSourceConfig(api_key="test-key")


class TestMailerLiteSourceClass:
    def test_source_type(self) -> None:
        assert MailerLiteSource().source_type == ExternalDataSourceType.MAILERLITE

    def test_source_config_fields(self) -> None:
        config = MailerLiteSource().get_source_config
        assert config.label == "MailerLite"
        assert config.unreleasedSource is not True
        assert [field.name for field in config.fields] == ["api_key"]
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD

    def test_get_schemas_are_all_full_refresh(self) -> None:
        schemas = MailerLiteSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = MailerLiteSource().get_schemas(_config(), team_id=1, names=["subscribers", "groups"])
        assert {s.name for s in schemas} == {"subscribers", "groups"}

    @pytest.mark.parametrize(
        ("valid", "expected_ok"),
        [(True, True), (False, False)],
    )
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.validate_mailerlite_credentials",
            return_value=valid,
        ):
            ok, error = MailerLiteSource().validate_credentials(_config(), team_id=1)
            assert ok is expected_ok
            assert (error is None) is expected_ok

    def test_validate_credentials_uses_schema_path(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.validate_mailerlite_credentials",
            return_value=True,
        ) as mock_validate:
            MailerLiteSource().validate_credentials(_config(), team_id=1, schema_name="groups")
            assert mock_validate.call_args.args == ("test-key", "/groups")

    def test_get_non_retryable_errors_cover_auth(self) -> None:
        errors = MailerLiteSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.logger = MagicMock()
        manager = MailerLiteSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MailerLiteResumeConfig

    def test_source_for_pipeline_plumbing(self) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "subscribers"
        inputs.logger = MagicMock()
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.mailerlite_source"
        ) as mock_source:
            MailerLiteSource().source_for_pipeline(_config(), manager, inputs)
            mock_source.assert_called_once_with(
                api_key="test-key",
                endpoint="subscribers",
                logger=inputs.logger,
                resumable_source_manager=manager,
            )
