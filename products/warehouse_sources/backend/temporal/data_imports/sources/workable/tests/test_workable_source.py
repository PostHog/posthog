from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WorkableSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workable import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.source import WorkableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable import WorkableResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> WorkableSourceConfig:
    return WorkableSourceConfig(subdomain="acme", api_token="tok")


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert WorkableSource().source_type == ExternalDataSourceType.WORKABLE

    def test_config_basics(self) -> None:
        config = WorkableSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.HR___RECRUITING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Stays hidden from users until the source is signed off.
        assert config.unreleasedSource is True

    def test_fields(self) -> None:
        field_names = {f.name for f in WorkableSource().get_source_config.fields}
        assert field_names == {"subdomain", "api_token"}

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Retargeting the subdomain must re-require the token (it's where the token is sent).
        assert WorkableSource().connection_host_fields == ["subdomain"]

    def test_api_token_field_is_secret(self) -> None:
        token_field = next(f for f in WorkableSource().get_source_config.fields if f.name == "api_token")
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.secret is True


class TestSchemas:
    def test_lists_all_endpoints(self) -> None:
        names = {s.name for s in WorkableSource().get_schemas(_config(), team_id=1)}
        assert names == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("jobs", True),
            ("candidates", True),
            ("members", False),
            ("recruiters", False),
            ("stages", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in WorkableSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].supports_append is expected_incremental

    def test_incremental_endpoints_offer_updated_and_created(self) -> None:
        schemas = {s.name: s for s in WorkableSource().get_schemas(_config(), team_id=1)}
        fields = {f["field"] for f in schemas["candidates"].incremental_fields}
        assert fields == {"updated_at", "created_at"}

    def test_names_filter(self) -> None:
        schemas = WorkableSource().get_schemas(_config(), team_id=1, names=["jobs"])
        assert [s.name for s in schemas] == ["jobs"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            # (status, ok, schema_name, expected_valid)
            ("ok_create", 200, True, None, True),
            ("ok_schema", 200, True, "candidates", True),
            ("unauthorized_create", 401, False, None, False),
            ("unauthorized_schema", 401, False, "candidates", False),
            # 403 = valid token missing a scope: accepted at create, rejected for a specific schema.
            ("forbidden_create_accepted", 403, False, None, True),
            ("forbidden_schema_rejected", 403, False, "candidates", False),
        ]
    )
    def test_credential_status_mapping(
        self, _name: str, status: int, ok: bool, schema_name: str | None, expected_valid: bool
    ) -> None:
        with mock.patch.object(source_module, "validate_workable_credentials", lambda *_a, **_k: (status, ok)):
            valid, _msg = WorkableSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert valid is expected_valid

    def test_invalid_subdomain_is_a_failure(self) -> None:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise ValueError("Invalid Workable subdomain")

        with mock.patch.object(source_module, "validate_workable_credentials", _raise):
            valid, msg = WorkableSource().validate_credentials(_config(), team_id=1)
        assert valid is False
        assert "subdomain" in (msg or "")


class TestMisc:
    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = WorkableSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = WorkableSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WorkableResumeConfig

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = WorkableSource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_source_for_pipeline_plumbs_arguments(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(source_module, "workable_source", fake_source)

        inputs = MagicMock()
        inputs.schema_name = "candidates"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = "updated_at"
        manager = MagicMock()

        result: Any = WorkableSource().source_for_pipeline(_config(), manager, inputs)
        assert result == "response"
        assert captured["subdomain"] == "acme"
        assert captured["api_token"] == "tok"
        assert captured["endpoint"] == "candidates"
        assert captured["incremental_field"] == "updated_at"
        assert captured["db_incremental_field_last_value"] == "2026-01-01"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(source_module, "workable_source", lambda **kwargs: captured.update(kwargs))

        inputs = MagicMock()
        inputs.schema_name = "members"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.incremental_field = None

        WorkableSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert captured["db_incremental_field_last_value"] is None
