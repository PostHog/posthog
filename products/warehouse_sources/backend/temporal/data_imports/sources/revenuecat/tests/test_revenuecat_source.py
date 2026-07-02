from collections.abc import Iterable
from typing import cast

from unittest.mock import MagicMock, patch

import pyarrow as pa

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RevenueCatSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    CUSTOMER_RESOURCE_NAME,
    EVENT_RESOURCE_NAME,
    RESOURCE_TO_REVENUECAT_EVENT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat import (
    RevenueCatResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.settings import (
    REVENUECAT_API_ENDPOINTS,
    REVENUECAT_API_SCHEMA_NAMES,
    REVENUECAT_WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source import (
    RevenueCatSource,
    _webhook_table_transformer,
)


def _config(api_key: str = "sk_test", project_id: str = "proj_test") -> RevenueCatSourceConfig:
    return RevenueCatSourceConfig(secret_api_key=api_key, project_id=project_id)


class TestRevenueCatSourceConfigFields:
    def test_get_source_config_exposes_required_secret_api_key_and_project_id(self):
        source = RevenueCatSource()
        cfg = source.get_source_config

        names = {f.name for f in cfg.fields}
        assert names == {"secret_api_key", "project_id"}

        api_key_field = next(f for f in cfg.fields if f.name == "secret_api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True

        project_field = next(f for f in cfg.fields if f.name == "project_id")
        assert isinstance(project_field, SourceFieldInputConfig)
        assert project_field.required is True
        assert project_field.secret is False

    def test_get_source_config_declares_authorization_header_as_webhook_field(self):
        source = RevenueCatSource()
        cfg = source.get_source_config

        assert cfg.webhookFields is not None
        webhook_field_names = {f.name for f in cfg.webhookFields}
        assert "authorization_header" in webhook_field_names

        auth_field = next(f for f in cfg.webhookFields if f.name == "authorization_header")
        assert isinstance(auth_field, SourceFieldInputConfig)
        assert auth_field.required is True
        assert auth_field.secret is True


class TestRevenueCatSourceWebhookResourceMap:
    def test_wildcard_funnels_all_events_into_one_table(self):
        source = RevenueCatSource()
        mapping = source.webhook_resource_map

        # Single events table — every webhook delivery is routed here regardless
        # of `event.type`. The wildcard sentinel lets the Hog template skip
        # per-type lookup.
        assert mapping == RESOURCE_TO_REVENUECAT_EVENT_TYPE
        assert mapping[EVENT_RESOURCE_NAME] == "*"


class TestRevenueCatSourceGetSchemas:
    def test_includes_both_webhook_and_api_schemas(self):
        source = RevenueCatSource()

        schemas = source.get_schemas(_config(), team_id=1)

        names = {s.name for s in schemas}
        for name in REVENUECAT_WEBHOOK_SCHEMA_NAMES:
            assert name in names, f"missing webhook schema: {name}"
        for name in REVENUECAT_API_SCHEMA_NAMES:
            assert name in names, f"missing api schema: {name}"

    def test_only_events_schema_supports_webhooks(self):
        source = RevenueCatSource()

        schemas = source.get_schemas(_config(), team_id=1)

        webhook_supported = {s.name for s in schemas if s.supports_webhooks}
        assert webhook_supported == set(REVENUECAT_WEBHOOK_SCHEMA_NAMES)

    def test_filters_by_names_argument(self):
        source = RevenueCatSource()

        schemas = source.get_schemas(_config(), team_id=1, names=["customers", "events"])

        assert {s.name for s in schemas} == {"customers", "events"}


class TestRevenueCatSourceCreateWebhook:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.create_webhook"
    )
    def test_delegates_to_api_client_without_authorization_header(self, mock_create):
        mock_create.return_value = WebhookCreationResult(success=True, pending_inputs=["authorization_header"])
        source = RevenueCatSource()

        result = source.create_webhook(_config("k", "p"), "https://example.com/h", team_id=1)

        assert result.success is True
        assert result.pending_inputs == ["authorization_header"]
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["project_id"] == "p"
        assert kwargs["webhook_url"] == "https://example.com/h"


class TestRevenueCatSourceWebhookInputsUpdated:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.create_webhook"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.delete_webhook"
    )
    def test_recreates_integration_when_authorization_header_provided(self, mock_delete, mock_create):
        # RevenueCat's API doesn't let you update the auth header on an existing
        # integration in-place, so the source must delete + recreate to bind a
        # new header value. Guard against regressions where we accidentally
        # short-circuit one of the two calls.
        mock_delete.return_value = WebhookDeletionResult(success=True)
        mock_create.return_value = WebhookCreationResult(success=True)
        source = RevenueCatSource()

        success, error = source.webhook_inputs_updated(
            _config("k", "p"),
            "https://example.com/h",
            team_id=1,
            inputs={"authorization_header": "Bearer my-secret"},
        )

        assert success is True
        assert error is None
        mock_delete.assert_called_once_with("k", "p", "https://example.com/h")
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["authorization_header_value"] == "Bearer my-secret"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.create_webhook"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.delete_webhook"
    )
    def test_skips_recreate_when_authorization_header_missing(self, mock_delete, mock_create):
        source = RevenueCatSource()

        success, error = source.webhook_inputs_updated(_config(), "https://example.com/h", team_id=1, inputs={})

        assert success is True
        assert error is None
        mock_delete.assert_not_called()
        mock_create.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.create_webhook"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.delete_webhook"
    )
    def test_propagates_delete_failure(self, mock_delete, mock_create):
        mock_delete.return_value = WebhookDeletionResult(success=False, error="boom")
        source = RevenueCatSource()

        success, error = source.webhook_inputs_updated(
            _config(), "https://example.com/h", team_id=1, inputs={"authorization_header": "x"}
        )

        assert success is False
        assert error == "boom"
        mock_create.assert_not_called()


class TestRevenueCatSourceDeleteWebhook:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.delete_webhook"
    )
    def test_delegates_to_api_client(self, mock_delete):
        mock_delete.return_value = WebhookDeletionResult(success=True)
        source = RevenueCatSource()

        result = source.delete_webhook(_config("k", "p"), "https://example.com/h", team_id=1)

        assert result.success is True
        mock_delete.assert_called_once_with("k", "p", "https://example.com/h")


class TestRevenueCatSourceSyncWebhookEvents:
    """RevenueCat has no provider-side event subscription to reconcile — it inherits the
    `WebhookSource` defaults, which are a no-op."""

    def test_get_desired_webhook_events_is_none(self):
        source = RevenueCatSource()
        assert source.get_desired_webhook_events(_config("k", "p"), ["events"]) is None

    def test_sync_webhook_events_is_noop_success(self):
        source = RevenueCatSource()
        result = source.sync_webhook_events(
            _config("k", "p"), "https://example.com/h", team_id=1, eligible_schema_names=["events"]
        )
        assert result.success is True
        assert result.error is None


class TestRevenueCatSourceExternalWebhookInfo:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.get_external_webhook_info"
    )
    def test_delegates_to_api_client(self, mock_info):
        mock_info.return_value = ExternalWebhookInfo(exists=True, status="enabled")
        source = RevenueCatSource()

        info = source.get_external_webhook_info(_config("k", "p"), "https://example.com/h", team_id=1)

        assert info is not None
        assert info.exists is True
        mock_info.assert_called_once_with("k", "p", "https://example.com/h")


class TestRevenueCatSourceValidateCredentials:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.validate_credentials"
    )
    def test_delegates_to_api_client(self, mock_validate):
        mock_validate.return_value = (True, None)
        source = RevenueCatSource()

        success, error = source.validate_credentials(_config("k", "p"), team_id=1)

        assert success is True
        assert error is None
        mock_validate.assert_called_once_with("k", "p")


class TestRevenueCatSourcePipelineDispatch:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.iterate_list_endpoint"
    )
    def test_api_schema_routes_to_iterate_list_endpoint(self, mock_iter):
        mock_iter.return_value = iter([{"id": "cus_1"}, {"id": "cus_2"}])
        source = RevenueCatSource()
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.logger = MagicMock()

        manager = MagicMock()
        manager.can_resume.return_value = False
        response = source.source_for_pipeline(_config("k", "p"), manager, inputs)

        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        # Customers partition by `first_seen_at` (they have no `created_at`) —
        # `iterate_list_endpoint` normalizes that ms epoch field to Unix seconds.
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["first_seen_at"]

        rows = list(cast(Iterable[dict[str, str]], response.items()))
        assert rows == [{"id": "cus_1"}, {"id": "cus_2"}]
        mock_iter.assert_called_once()
        kwargs = mock_iter.call_args.kwargs
        assert kwargs["api_key"] == "k"
        assert kwargs["project_id"] == "p"
        assert kwargs["path_suffix"] == "/customers"
        assert kwargs["endpoint_name"] == "customers"
        # The partition field must be handed to the iterator so it gets
        # normalized ms->seconds; for customers that's `first_seen_at`.
        assert kwargs["timestamp_fields"] == ("first_seen_at",)
        assert kwargs["starting_after"] is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.iterate_list_endpoint"
    )
    def test_resumes_from_saved_state_when_endpoint_matches(self, mock_iter):
        # Resumable state should only be honored when the saved endpoint matches
        # the one we're currently syncing — otherwise we'd replay a customers
        # cursor against products and skip rows.
        mock_iter.return_value = iter([])
        source = RevenueCatSource()
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.logger = MagicMock()

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = RevenueCatResumeConfig(endpoint="customers", starting_after="cus_50")

        response = source.source_for_pipeline(_config("k", "p"), manager, inputs)
        list(cast(Iterable[dict[str, str]], response.items()))

        kwargs = mock_iter.call_args.kwargs
        assert kwargs["starting_after"] == "cus_50"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.source.api_client.iterate_list_endpoint"
    )
    def test_ignores_resume_state_from_different_endpoint(self, mock_iter):
        mock_iter.return_value = iter([])
        source = RevenueCatSource()
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.logger = MagicMock()

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = RevenueCatResumeConfig(endpoint="products", starting_after="prod_10")

        response = source.source_for_pipeline(_config("k", "p"), manager, inputs)
        list(cast(Iterable[dict[str, str]], response.items()))

        kwargs = mock_iter.call_args.kwargs
        assert kwargs["starting_after"] is None

    def test_events_schema_routes_to_webhook_source_response(self):
        source = RevenueCatSource()
        inputs = MagicMock()
        inputs.schema_name = EVENT_RESOURCE_NAME
        inputs.logger = MagicMock()

        sentinel = cast(SourceResponse, "WEBHOOK_RESPONSE")
        with patch.object(source, "_webhook_source_response", return_value=sentinel) as mock_webhook:
            result = source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert result is sentinel
        mock_webhook.assert_called_once_with(inputs)

    def test_every_api_endpoint_partitions_by_stable_timestamp(self):
        # Customers have no `created_at`; they partition by `first_seen_at`. Every
        # other endpoint partitions by `created_at`. Both are stable per row.
        for name, endpoint in REVENUECAT_API_ENDPOINTS.items():
            expected = ["first_seen_at"] if name == CUSTOMER_RESOURCE_NAME else ["created_at"]
            assert endpoint.partition_keys == expected, name
            assert endpoint.primary_keys == ["id"], name


class TestRevenueCatWebhookTableTransformer:
    def test_lifts_event_fields_and_preserves_api_version(self):
        table = table_from_py_list(
            [
                {
                    "api_version": "1.0",
                    "event": {
                        "id": "evt-1",
                        "type": "INITIAL_PURCHASE",
                        "app_user_id": "user-1",
                        "product_id": "com.subscription.weekly",
                        "store": "APP_STORE",
                        "event_timestamp_ms": 1658726374000,
                        "purchased_at_ms": 1658726374000,
                    },
                }
            ]
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert len(rows) == 1
        assert rows[0]["id"] == "evt-1"
        assert rows[0]["type"] == "INITIAL_PURCHASE"
        assert rows[0]["app_user_id"] == "user-1"
        assert rows[0]["store"] == "APP_STORE"
        assert rows[0]["api_version"] == "1.0"
        # Original ms field preserved unchanged for callers that care about
        # sub-second precision; `created_at` is the derived seconds value used
        # for partitioning.
        assert rows[0]["event_timestamp_ms"] == 1658726374000
        assert rows[0]["created_at"] == 1658726374

    def test_skips_created_at_derivation_when_event_timestamp_ms_missing(self):
        # Older RevenueCat events or test deliveries may omit the timestamp
        # entirely. Don't synthesize a fake `created_at` value — the partition
        # layer falls back to "1970-01" for missing keys, which is a clearer
        # signal of the missing field than a zero value would be.
        table = table_from_py_list([{"api_version": "1.0", "event": {"id": "evt-1", "type": "TEST"}}])

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert rows[0]["id"] == "evt-1"
        assert "created_at" not in rows[0]

    def test_handles_event_as_json_string(self):
        # Defensive: if upstream serializes `event` as a JSON string, we still
        # parse it correctly.
        table = pa.table(
            {
                "api_version": ["1.0"],
                "event": ['{"id": "evt-2", "type": "RENEWAL", "app_user_id": "u"}'],
            }
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert rows == [{"id": "evt-2", "type": "RENEWAL", "app_user_id": "u", "api_version": "1.0"}]

    def test_skips_rows_with_null_event(self):
        table = pa.table(
            {
                "api_version": ["1.0", "1.0"],
                "event": [None, {"id": "evt-4", "type": "RENEWAL"}],
            }
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert rows == [{"id": "evt-4", "type": "RENEWAL", "api_version": "1.0"}]

    def test_returns_empty_when_event_column_missing(self):
        table = pa.table({"api_version": ["1.0"]})

        result = _webhook_table_transformer(table)

        assert result.num_rows == 0
