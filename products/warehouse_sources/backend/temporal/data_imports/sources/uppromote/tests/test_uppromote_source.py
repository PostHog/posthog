from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.source import UpPromoteSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.source"


class TestUpPromoteSource:
    def setup_method(self) -> None:
        self.source = UpPromoteSource()

    @parameterized.expand(
        [
            (True, None),
            (False, "UpPromote rejected the API key"),
        ]
    )
    def test_validate_credentials_delegates_to_transport(self, valid: bool, error: str | None) -> None:
        with patch(f"{SOURCE_MODULE}.validate_uppromote_credentials", return_value=(valid, error)) as mock_validate:
            result, message = self.source.validate_credentials(MagicMock(api_key="key-1"), team_id=1)

        mock_validate.assert_called_once_with("key-1")
        assert result is valid
        assert message == error

    def test_webhook_resource_map_routes_object_types(self) -> None:
        assert self.source.webhook_resource_map == {
            "affiliates": "affiliate",
            "referrals": "referral",
            "payments_paid": "payment",
        }

    def test_webhook_template_routes_and_verifies_signature(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-uppromote"
        assert template.type == "warehouse_source_webhook"
        input_keys = {i["key"] for i in template.inputs_schema}
        assert {"signing_secret", "bypass_signature_check", "schema_mapping", "source_id"} <= input_keys
        assert "x-uppromote-signature" in template.code
        assert "produceToWarehouseWebhooks" in template.code

    def test_desired_webhook_events_exclude_unmergeable_status_changed(self) -> None:
        events = self.source.get_desired_webhook_events(MagicMock(), ["affiliates"])
        assert events is not None
        assert set(events) == {
            "affiliate.new",
            "affiliate.approved",
            "affiliate.inactive",
            "referral.new",
            "referral.approved",
            "referral.denied",
            "payment.paid",
        }
        # Status-changed payloads are {previous_status, current_status} diffs and can't be
        # merged into a table row.
        assert not any(event.endswith("status-changed") for event in events)

    @parameterized.expand(
        [
            ("create_webhook", "create_uppromote_webhook"),
            ("delete_webhook", "delete_uppromote_webhook"),
            ("get_external_webhook_info", "get_uppromote_webhook_info"),
        ]
    )
    def test_webhook_management_delegates_to_transport(self, method: str, transport_fn: str) -> None:
        with patch(f"{SOURCE_MODULE}.{transport_fn}") as mock_fn:
            getattr(self.source, method)(MagicMock(api_key="key-1"), "https://hooks.posthog.com/x", team_id=1)

        mock_fn.assert_called_once_with("key-1", "https://hooks.posthog.com/x")

    def test_sync_webhook_events_passes_all_desired_events(self) -> None:
        with patch(f"{SOURCE_MODULE}.sync_uppromote_webhook_events") as mock_fn:
            self.source.sync_webhook_events(
                MagicMock(api_key="key-1"), "https://hooks.posthog.com/x", team_id=1, eligible_schema_names=[]
            )

        api_key, webhook_url, events = mock_fn.call_args.args
        assert api_key == "key-1"
        assert webhook_url == "https://hooks.posthog.com/x"
        assert len(events) == 7
