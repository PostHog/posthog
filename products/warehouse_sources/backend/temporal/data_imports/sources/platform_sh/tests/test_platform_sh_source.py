from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.platform_sh import (
    AUTH_FAILED_MESSAGE,
    PlatformShResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.source import PlatformShSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPlatformShSourceConfig:
    def test_source_type(self) -> None:
        assert PlatformShSource().source_type == ExternalDataSourceType.PLATFORMSH

    def test_source_config_shape(self) -> None:
        config = PlatformShSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/platform-sh"

    def test_token_and_platform_fields(self) -> None:
        fields = PlatformShSource().get_source_config.fields
        assert fields is not None and len(fields) == 2
        token_field, platform_field = fields
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True
        assert isinstance(platform_field, SourceFieldSelectConfig)
        assert platform_field.name == "platform"
        assert {option.value for option in platform_field.options} == {"platform_sh", "upsun"}
        assert platform_field.defaultValue == "platform_sh"

    def test_platform_is_a_connection_host_field(self) -> None:
        # `platform` retargets which vendor host the stored token is sent to, so changing it must
        # force the editor to re-enter the secret.
        assert PlatformShSource().connection_host_fields == ["platform"]


class TestPlatformShGetSchemas:
    def test_only_activities_supports_incremental(self) -> None:
        schemas = {s.name: s for s in PlatformShSource().get_schemas(mock.Mock(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)

        activities = schemas["activities"]
        assert activities.supports_incremental is True
        assert activities.supports_append is True
        assert [f["field"] for f in activities.incremental_fields] == ["created_at"]
        # Activities mutate after creation; the lookback makes each sync re-read a trailing window
        # so completed states aren't frozen at first-imported values.
        assert activities.default_incremental_lookback_seconds == 86400

        for name, schema in schemas.items():
            if name == "activities":
                continue
            assert not schema.supports_incremental and not schema.supports_append
            assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = PlatformShSource().get_schemas(mock.Mock(), team_id=1, names=["projects", "activities"])
        assert {s.name for s in schemas} == {"projects", "activities"}


class TestPlatformShValidateCredentials:
    def test_plumbs_to_transport(self) -> None:
        config = mock.Mock(api_token="tok", platform="upsun")
        with mock.patch.object(
            source_module, "validate_platform_sh_credentials", return_value=(True, None)
        ) as validate_mock:
            assert PlatformShSource().validate_credentials(config, team_id=1) == (True, None)
        assert validate_mock.call_args.args[:2] == ("tok", "upsun")

    def test_failure_propagates_message(self) -> None:
        config = mock.Mock(api_token="bad", platform="platform_sh")
        with mock.patch.object(
            source_module, "validate_platform_sh_credentials", return_value=(False, "Invalid Platform.sh API token")
        ):
            ok, error = PlatformShSource().validate_credentials(config, team_id=1)
        assert ok is False
        assert error == "Invalid Platform.sh API token"


class TestPlatformShNonRetryableErrors:
    def test_covers_auth_failures_on_both_hosts(self) -> None:
        # Missing any of these means a permanently-bad credential retries forever.
        errors = PlatformShSource().get_non_retryable_errors()
        assert AUTH_FAILED_MESSAGE in errors
        for host in ("https://api.platform.sh", "https://api.upsun.com"):
            assert f"401 Client Error: Unauthorized for url: {host}" in errors
            assert f"403 Client Error: Forbidden for url: {host}" in errors


class TestPlatformShCanonicalDescriptions:
    def test_covers_every_endpoint(self) -> None:
        descriptions = PlatformShSource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)


class TestPlatformShResumableWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = mock.Mock()
        inputs.logger = mock.Mock()
        manager = PlatformShSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PlatformShResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        config = mock.Mock(api_token="tok", platform="upsun")
        inputs = mock.Mock(
            schema_name="activities",
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value="2026-07-01T00:00:00+00:00",
        )
        inputs.logger = mock.Mock()
        manager = mock.Mock()

        with mock.patch.object(source_module, "platform_sh_source") as source_mock:
            PlatformShSource().source_for_pipeline(config, manager, inputs)

        source_mock.assert_called_once_with(
            api_token="tok",
            platform="upsun",
            endpoint="activities",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value="2026-07-01T00:00:00+00:00",
        )
