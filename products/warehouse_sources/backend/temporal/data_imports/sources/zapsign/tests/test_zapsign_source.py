import datetime
from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.settings import DOCUMENTS_RESOURCE
from products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.source import ZapSignSource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.zapsign.zapsign"


def _source_inputs(
    schema_name: str = DOCUMENTS_RESOURCE,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=mock.MagicMock(),
        reset_pipeline=False,
    )


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

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()

        # ZapSign answers 403 for a bad token, so both auth statuses must permanently fail.
        assert "403 Client Error: Forbidden" in errors
        assert "401 Client Error: Unauthorized" in errors

    @parameterized.expand(
        [
            ("incremental", True, datetime.datetime(2026, 5, 1)),
            ("full_refresh", False, None),
        ]
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        config = mock.MagicMock(api_token="token-123", environment="production")
        inputs = _source_inputs(
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        resumable_manager = mock.MagicMock()
        webhook_manager = mock.MagicMock()
        expected = mock.MagicMock(spec=SourceResponse)

        with (
            mock.patch(f"{API_CLIENT_PATCH}.zapsign_source", return_value=expected) as zapsign_source,
            mock.patch.object(self.source, "get_webhook_source_manager", return_value=webhook_manager),
        ):
            response = self.source.source_for_pipeline(config, resumable_manager, inputs)

        assert response is expected
        zapsign_source.assert_called_once_with(
            api_token="token-123",
            environment="production",
            endpoint=DOCUMENTS_RESOURCE,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=resumable_manager,
            webhook_source_manager=webhook_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
