from collections.abc import Iterable
from typing import Literal, cast

from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source import (
    CustomerIOSource,
    _webhook_table_transformer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.customerio import (
    CustomerIOSourceConfig,
)


def _config(app_api_key: str = "test-key", region: Literal["us", "eu"] = "us") -> CustomerIOSourceConfig:
    return CustomerIOSourceConfig(app_api_key=app_api_key, region=region)


class TestCustomerIOSourceWebhookResourceMap:
    def test_keys_use_events_suffix_and_map_to_cio_object_types(self):
        source = CustomerIOSource()
        mapping = source.webhook_resource_map

        for schema_name in mapping:
            assert schema_name.endswith("_events"), schema_name

        assert mapping["customer_events"] == "customer"
        assert mapping["email_events"] == "email"
        assert mapping["in_app_events"] == "in_app"


class TestCustomerIOSourceGetSchemas:
    def test_filters_by_names_argument(self):
        source = CustomerIOSource()

        schemas = source.get_schemas(_config(), team_id=1, names=["broadcasts", "email_events"])

        assert {s.name for s in schemas} == {"broadcasts", "email_events"}


class TestCustomerIOSourceWebhookInputsUpdated:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source.api_client.enable_webhook"
    )
    def test_enables_webhook_when_signing_secret_is_provided(self, mock_enable):
        mock_enable.return_value = (True, None)
        source = CustomerIOSource()

        success, error = source.webhook_inputs_updated(
            _config(app_api_key="key", region="eu"),
            "https://example.com/h",
            team_id=1,
            inputs={"signing_secret": "shh"},
        )

        assert success is True
        assert error is None
        mock_enable.assert_called_once_with("key", "eu", "https://example.com/h")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source.api_client.enable_webhook"
    )
    def test_skips_enable_when_signing_secret_is_missing(self, mock_enable):
        source = CustomerIOSource()

        success, error = source.webhook_inputs_updated(
            _config(app_api_key="key", region="us"),
            "https://example.com/h",
            team_id=1,
            inputs={},
        )

        assert success is True
        assert error is None
        mock_enable.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source.api_client.enable_webhook"
    )
    def test_skips_enable_when_signing_secret_is_empty(self, mock_enable):
        source = CustomerIOSource()

        success, error = source.webhook_inputs_updated(
            _config(app_api_key="key", region="us"),
            "https://example.com/h",
            team_id=1,
            inputs={"signing_secret": ""},
        )

        assert success is True
        assert error is None
        mock_enable.assert_not_called()


class TestCustomerIOSourcePipelineDispatch:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source.api_client.iterate_list_endpoint"
    )
    def test_api_schema_routes_to_iterate_list_endpoint(self, mock_iter):
        mock_iter.return_value = iter([{"id": 1}, {"id": 2}])
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "broadcasts"
        inputs.logger = MagicMock()

        response = source.source_for_pipeline(_config(app_api_key="key", region="us"), inputs)

        assert response.name == "broadcasts"
        assert response.primary_keys == ["id"]

        # Verify the items() iterator triggers iterate_list_endpoint with the right endpoint.
        rows = list(cast(Iterable[dict[str, int]], response.items()))
        assert rows == [{"id": 1}, {"id": 2}]
        mock_iter.assert_called_once()
        kwargs = mock_iter.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"].path == "/v1/broadcasts"

    def test_webhook_schema_routes_to_webhook_source_response(self):
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "email_events"
        inputs.logger = MagicMock()

        sentinel = cast(SourceResponse, "WEBHOOK_RESPONSE")
        # Stub the webhook manager so we don't need a real one.
        with patch.object(source, "_webhook_source_response", return_value=sentinel) as mock_webhook:
            result = source.source_for_pipeline(_config(app_api_key="key"), inputs)

        assert result is sentinel
        mock_webhook.assert_called_once_with(inputs)

    def test_every_api_endpoint_has_partitioning_configured(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.constants import (
            CIO_API_ENDPOINTS,
        )

        for name, endpoint in CIO_API_ENDPOINTS.items():
            assert endpoint.partition_mode in ("datetime", "md5"), name
            assert endpoint.partition_keys, name
            if endpoint.partition_mode == "datetime":
                assert endpoint.partition_format is not None, name


class TestCustomerIOWebhookTableTransformer:
    def test_handles_data_as_json_string(self):
        # Defensive: if an upstream change serializes `data` as a JSON string instead
        # of a nested struct, we still parse it correctly.
        table = pa.table(
            {
                "event_id": ["evt-2"],
                "timestamp": [1777655416],
                "metric": ["opened"],
                "data": ['{"recipient": "a@example.com"}'],
            }
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert rows == [
            {"event_id": "evt-2", "timestamp": 1777655416, "metric": "opened", "recipient": "a@example.com"}
        ]

    def test_skips_rows_with_null_data(self):
        # A null `data` field would produce a row with no lifted columns — skip it
        # rather than emit a sparse row that can't be partitioned reliably.
        table = pa.table(
            {
                "event_id": ["evt-3", "evt-4"],
                "timestamp": [1, 2],
                "metric": ["sent", "clicked"],
                "data": [None, {"recipient": "b@example.com"}],
            }
        )

        result = _webhook_table_transformer(table)
        rows = result.to_pylist()

        assert rows == [{"event_id": "evt-4", "timestamp": 2, "metric": "clicked", "recipient": "b@example.com"}]

    def test_returns_empty_when_data_column_missing(self):
        table = pa.table({"event_id": ["evt-5"], "timestamp": [1]})

        result = _webhook_table_transformer(table)

        assert result.num_rows == 0
