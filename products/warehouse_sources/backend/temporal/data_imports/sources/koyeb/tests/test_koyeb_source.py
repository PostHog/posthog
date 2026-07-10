from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb import source as koyeb_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import KoyebResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.source import KoyebSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MagicMock:
    config = MagicMock()
    config.api_key = "tok"
    return config


class TestKoyebSourceClass:
    def test_source_type(self) -> None:
        assert KoyebSource().source_type == ExternalDataSourceType.KOYEB

    def test_source_config_stays_unreleased_alpha_with_api_key_field(self) -> None:
        config = KoyebSource().get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/koyeb"
        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key"]

    def test_only_time_windowed_endpoints_support_incremental(self) -> None:
        # instances and usage_details are the only endpoints Koyeb exposes a server-side time filter
        # for; marking anything else incremental would page the full history every run.
        schemas = {s.name: s for s in KoyebSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"instances", "usage_details"}

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = KoyebSource().get_schemas(_config(), team_id=1, names=["apps"])
        assert [s.name for s in schemas] == ["apps"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://app.koyeb.com/v1/apps?limit=100&offset=0",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://app.koyeb.com/v1/secrets?limit=100&offset=0",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = KoyebSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_transient_error_stays_retryable(self) -> None:
        non_retryable = KoyebSource().get_non_retryable_errors()
        assert not any(key in "500 Server Error: Internal Server Error" for key in non_retryable)

    @parameterized.expand(
        [
            # (validate returns), schema_name, expected_ok
            ((False, "Your Koyeb API token does not have permission to access this data"), None, True),
            ((False, "Your Koyeb API token does not have permission to access this data"), "secrets", False),
            ((False, "Invalid Koyeb API token"), None, False),
            ((True, None), None, True),
        ]
    )
    def test_validate_credentials_accepts_missing_scope_only_at_create(
        self, validate_result: tuple[bool, str | None], schema_name: str | None, expected_ok: bool
    ) -> None:
        # A scoped token (403) must connect at create — users may only grant scopes for the tables
        # they want — but a per-schema check must still surface the missing scope.
        with patch.object(koyeb_source_module, "validate_koyeb_credentials", return_value=validate_result):
            ok, _error = KoyebSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = KoyebSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KoyebResumeConfig

    def test_source_for_pipeline_plumbs_endpoint_and_incremental_value(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "instances"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        captured: dict = {}

        def fake_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        with patch.object(koyeb_source_module, "koyeb_source", side_effect=fake_source):
            KoyebSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["endpoint"] == "instances"
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"

    def test_source_for_pipeline_drops_incremental_value_when_not_incremental(self) -> None:
        # A full-refresh run must not forward a stale watermark that would trigger a server-side filter.
        inputs = MagicMock()
        inputs.schema_name = "apps"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        captured: dict = {}

        def fake_source(**kwargs: object):
            captured.update(kwargs)
            return MagicMock()

        with patch.object(koyeb_source_module, "koyeb_source", side_effect=fake_source):
            KoyebSource().source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
