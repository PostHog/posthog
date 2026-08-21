from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import DOCUMENTS_RESOURCE
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.source import ZapSignSource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign"


class TestZapSignSource:
    def setup_method(self) -> None:
        self.source = ZapSignSource()

    def test_webhook_resource_map_routes_documents_to_wildcard(self) -> None:
        assert self.source.webhook_resource_map == {DOCUMENTS_RESOURCE: "*"}

    def test_webhook_template_is_registered(self) -> None:
        template = self.source.webhook_template

        assert template is not None
        assert template.id == "template-warehouse-source-zapsign"
        assert template.type == "warehouse_source_webhook"

    def test_create_webhook_delegates_to_api_client(self) -> None:
        config = mock.MagicMock(api_token="token-123", environment="production")
        with mock.patch(f"{API_CLIENT_PATCH}.create_webhook") as create:
            self.source.create_webhook(config, "https://webhooks.posthog.com/dwh/abc", team_id=1)

        create.assert_called_once_with("token-123", "production", "https://webhooks.posthog.com/dwh/abc")

    def test_delete_webhook_reports_manual_removal(self) -> None:
        result = self.source.delete_webhook(mock.MagicMock(), "https://webhooks.posthog.com/dwh/abc", team_id=1)

        assert result.success is False
        assert "Delete it in ZapSign" in str(result.error)
