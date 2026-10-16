import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.veeqo import VeeqoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source import VeeqoSource


class TestVeeqoSourceNonRetryableErrors:
    def test_http_error_message_format_matches_patterns(self) -> None:
        # The patterns must match the exact message `raise_for_status` produces,
        # otherwise auth failures retry forever instead of failing permanently.
        for status, reason in ((401, "Unauthorized"), (403, "Forbidden")):
            response = requests.Response()
            response.status_code = status
            response.reason = reason
            response.url = "https://api.veeqo.com/orders?page=1"

            try:
                response.raise_for_status()
                raise AssertionError("raise_for_status did not raise")
            except requests.HTTPError as e:
                error_msg = str(e)

            patterns = VeeqoSource().get_non_retryable_errors()
            assert any(pattern in error_msg for pattern in patterns), (
                f"HTTPError message '{error_msg}' did not match any non-retryable pattern"
            )


class TestVeeqoSourceSchemas:
    def test_fanout_tables_are_opt_in(self) -> None:
        schemas = {schema.name: schema for schema in VeeqoSource().get_schemas(VeeqoSourceConfig(api_key="k"), 1)}

        assert not schemas["shipment_tracking_events"].should_sync_default
        assert not schemas["bundle_contents"].should_sync_default
        assert schemas["orders"].should_sync_default
