from typing import Any

import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailersend import (
    MailerSendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.source import MailerSendSource


def _config() -> MailerSendSourceConfig:
    return MailerSendSourceConfig.from_dict({"api_token": "mlsn.token"})


class TestGetSchemas:
    @parameterized.expand(
        [
            ("domains", False, False),
            ("recipients", False, False),
            ("templates", False, False),
            ("messages", False, False),
            ("activity", True, True),
            ("hard_bounces", False, False),
            ("spam_complaints", False, False),
            ("unsubscribes", False, False),
            # Append would add a duplicate row for the re-read last day on every sync.
            ("analytics_by_date", True, False),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, supports_append: bool
    ) -> None:
        schemas = {s.name: s for s in MailerSendSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is supports_incremental
        assert schemas[endpoint].supports_append is supports_append


class TestResumableWiring:
    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(MailerSendSource(), _config()).run(
            "activity",
            [
                ScriptedResponse(json={"data": [{"id": "d1"}], "links": {"next": None}}),
                ScriptedResponse(json={"data": [{"id": "a1"}], "links": {"next": None}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.paths == ["/v1/domains", "/v1/activity/d1"]
        assert result.requests[1].headers["authorization"] == "Bearer mlsn.token"
        assert result.requests[1].param("date_from") == "1780272000"
        assert result.rows[0]["id"] == "a1"

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
    def test_activity_documents_injected_domain_id(self) -> None:
        # domain_id is added by PostHog, not MailerSend, so it must be documented for the AI agent.
        activity = MailerSendSource().get_canonical_descriptions()["activity"]
        assert "domain_id" in activity["columns"]
