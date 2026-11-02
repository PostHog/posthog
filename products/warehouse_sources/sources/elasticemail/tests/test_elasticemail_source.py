from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.source import ElasticemailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.elasticemail import (
    ElasticemailSourceConfig,
)


class TestGetSchemas:
    @parameterized.expand(
        [
            ("contacts",),
            ("lists",),
            ("segments",),
            ("campaigns",),
            ("templates",),
            ("suppressions",),
            ("list_contacts",),
            ("campaign_statistics",),
            ("verifications",),
        ]
    )
    def test_non_event_endpoints_are_full_refresh(self, endpoint: str) -> None:
        schemas = {s.name: s for s in ElasticemailSource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    @parameterized.expand([("statistics", True, False), ("events", False, True)])
    def test_time_filtered_endpoints(self, endpoint: str, incremental: bool, append: bool) -> None:
        schema = {s.name: s for s in ElasticemailSource().get_schemas(MagicMock(), team_id=1)}[endpoint]
        assert schema.supports_incremental is incremental
        assert schema.supports_append is append


class TestValidateCredentials:
    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_elasticemail_credentials", lambda *a, **k: False)
        valid, error = ElasticemailSource().validate_credentials(SimpleNamespace(api_key="bad"), team_id=1)  # type: ignore[arg-type]
        assert valid is False
        assert error == "Invalid Elastic Email API key"

    @parameterized.expand(
        [
            ("templates", "/templates", {"scopeType": ["Personal", "Global"]}),
            ("list_contacts", "/lists", {}),
        ]
    )
    def test_per_schema_probe_uses_endpoint_path(
        self, schema_name: str, expected_path: str, expected_params: dict[str, Any]
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_validate(api_key: str, path: str = "/statistics", extra_params: Any = None) -> bool:
            captured["path"] = path
            captured["extra_params"] = extra_params
            return True

        with patch.object(source_module, "validate_elasticemail_credentials", fake_validate):
            ElasticemailSource().validate_credentials(
                SimpleNamespace(api_key="key"),  # type: ignore[arg-type]
                team_id=1,
                schema_name=schema_name,
            )
        assert captured["path"] == expected_path
        assert captured["extra_params"] == expected_params


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("server_error", "ElasticEmailRetryableError: status=500"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = ElasticemailSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestResumableAndCanonical:
    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(ElasticemailSource(), ElasticemailSourceConfig(api_key="key")).run(
            "events",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "events"
        assert response.primary_keys == ["TransactionID", "MsgID", "EventType", "EventDate"]
        assert result.requests[0].param("from") == "2026-01-01T00:00:00"
