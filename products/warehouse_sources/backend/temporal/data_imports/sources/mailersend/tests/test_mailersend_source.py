from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailersend import (
    MailerSendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.source import MailerSendSource


def _config() -> MailerSendSourceConfig:
    return MailerSendSourceConfig.from_dict({"api_token": "mlsn.token"})


class TestGetSchemas:
    def test_only_activity_is_incremental(self) -> None:
        # Only the Activity endpoint exposes a server-side date filter; the rest are full refresh.
        schemas = {s.name: s for s in MailerSendSource().get_schemas(_config(), team_id=1)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"activity"}


class TestResumableWiring:
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
