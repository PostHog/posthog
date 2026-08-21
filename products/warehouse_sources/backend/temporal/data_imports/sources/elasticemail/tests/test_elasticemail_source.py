from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.source import ElasticemailSource


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
