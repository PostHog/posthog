from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail import (
    ElasticEmailResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.source import ElasticemailSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert ElasticemailSource().source_type == ExternalDataSourceType.ELASTICEMAIL

    def test_get_source_config(self) -> None:
        config = ElasticemailSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.fields is not None
        assert len(config.fields) == 1
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True


class TestGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = ElasticemailSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_filters_by_names(self) -> None:
        schemas = ElasticemailSource().get_schemas(MagicMock(), team_id=1, names=["contacts", "events"])
        assert {s.name for s in schemas} == {"contacts", "events"}

    def test_events_are_append_only(self) -> None:
        schemas = {s.name: s for s in ElasticemailSource().get_schemas(MagicMock(), team_id=1)}
        events = schemas["events"]
        # Events are immutable and the only endpoint with a server-side time filter → append, not merge.
        assert events.supports_incremental is False
        assert events.supports_append is True
        assert [f["field"] for f in events.incremental_fields] == ["EventDate"]

    @parameterized.expand([("contacts",), ("lists",), ("segments",), ("campaigns",), ("templates",), ("suppressions",)])
    def test_non_event_endpoints_are_full_refresh(self, endpoint: str) -> None:
        schemas = {s.name: s for s in ElasticemailSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_elasticemail_credentials", lambda *a, **k: True)
        valid, error = ElasticemailSource().validate_credentials(SimpleNamespace(api_key="key"), team_id=1)  # type: ignore[arg-type]
        assert valid is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_elasticemail_credentials", lambda *a, **k: False)
        valid, error = ElasticemailSource().validate_credentials(SimpleNamespace(api_key="bad"), team_id=1)  # type: ignore[arg-type]
        assert valid is False
        assert error == "Invalid Elastic Email API key"

    def test_per_schema_probe_uses_endpoint_path(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_validate(api_key: str, path: str = "/statistics", extra_params: Any = None) -> bool:
            captured["path"] = path
            captured["extra_params"] = extra_params
            return True

        monkeypatch.setattr(source_module, "validate_elasticemail_credentials", fake_validate)
        ElasticemailSource().validate_credentials(SimpleNamespace(api_key="key"), team_id=1, schema_name="templates")  # type: ignore[arg-type]
        assert captured["path"] == "/templates"
        assert captured["extra_params"] == {"scopeType": ["Personal", "Global"]}


class TestNonRetryableErrors:
    def test_auth_error_is_non_retryable(self) -> None:
        errors = ElasticemailSource().get_non_retryable_errors()
        observed = (
            'ElasticEmailAuthError: Elastic Email API authentication failed (HTTP 400): {"Error":"APIKey Expired"}'
        )
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.elasticemail.com', port=443): Read timed out."),
            ("server_error", "ElasticEmailRetryableError: status=500"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = ElasticemailSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestResumableAndCanonical:
    def test_resumable_manager_is_bound_to_resume_config(self) -> None:
        inputs = SimpleNamespace(logger=MagicMock())
        manager = ElasticemailSource().get_resumable_source_manager(inputs)  # type: ignore[arg-type]
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ElasticEmailResumeConfig

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = ElasticemailSource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = SimpleNamespace(
            schema_name="events",
            logger=MagicMock(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )
        response = ElasticemailSource().source_for_pipeline(
            SimpleNamespace(api_key="key"),  # type: ignore[arg-type]
            MagicMock(),
            inputs,  # type: ignore[arg-type]
        )
        assert response.name == "events"
        assert response.primary_keys == ["TransactionID", "MsgID", "EventType", "EventDate"]
