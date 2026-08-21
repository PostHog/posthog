from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailgun import (
    MailgunSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_RESOURCE_KEY,
    WEBHOOK_TYPES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source import MailgunSource

WEBHOOK_URL = "https://us.posthog.com/public/webhooks/abc"


def _response(payload: dict[str, Any]) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = payload
    response.status_code = 200
    response.ok = True
    response.headers = {}
    return response


class TestMailgunSource:
    def setup_method(self):
        self.source = MailgunSource()
        self.team_id = 123
        self.config = MailgunSourceConfig(api_key="key-123", region="us")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == {*ENDPOINTS, WEBHOOK_EVENTS_ENDPOINT}
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the Events API exposes a server-side timestamp filter.
        assert incremental == {"events"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Mailgun API key or region"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.validate_mailgun_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_version_declaration_defaults_to_v4_with_v3_supported(self):
        # Mailgun versions each resource by URL path; both labels resolve to the same requests
        # (see test_request_paths_are_version_independent), so the default tracks the newest label.
        assert self.source.supported_versions == ("v3", "v4")
        assert self.source.default_version == "v4"
        assert self.source.deprecated_versions == ()

    @pytest.mark.parametrize("pinned_version", [None, "v3", "v4"])
    @pytest.mark.parametrize(
        "endpoint, expected_paths",
        [
            # domains lists at /v4 under every pin; the resources with no v4 route stay /v3.
            ("domains", ["/v4/domains"]),
            ("events", ["/v4/domains", "/v3/a.com/events"]),
            ("bounces", ["/v4/domains", "/v3/a.com/bounces"]),
            ("mailing_lists", ["/v3/lists/pages"]),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun.make_tracked_session")
    def test_request_paths_are_version_independent(self, mock_session, endpoint, expected_paths, pinned_version):
        # The pin is declaration-only: a v3 and a v4 source must hit the exact same URLs, so a
        # future accidental per-version URL branch (or a repin silently switching a table's route)
        # would fail here.
        requests_made: list[str] = []

        def fake_get(url, **kwargs):
            requests_made.append(url)
            if "/v4/domains" in url:
                return _response({"items": [{"name": "a.com"}]})
            return _response({"items": [], "paging": {}})

        mock_session.return_value.get.side_effect = fake_get

        inputs = mock.MagicMock()
        inputs.schema_name = endpoint
        inputs.api_version = pinned_version
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.incremental_field = None
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = self.source.source_for_pipeline(self.config, manager, inputs)
        list(cast(Iterable[Any], response.items()))

        assert [urlsplit(url).path for url in requests_made] == expected_paths

    def test_only_the_webhook_table_is_webhook_capable(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # A polled schema switched to webhook mode stops polling, and Mailgun has no webhook for
        # the `rejected`, `stored` and list-upload events the Events API returns, so turning
        # webhooks on for `events` would quietly stop collecting them.
        assert {name for name, schema in schemas.items() if schema.supports_webhooks} == {WEBHOOK_EVENTS_ENDPOINT}
        assert {name for name, schema in schemas.items() if schema.webhook_only} == {WEBHOOK_EVENTS_ENDPOINT}

    def test_webhook_resource_map_matches_the_template_routing_key(self):
        assert self.source.webhook_resource_map == {WEBHOOK_EVENTS_ENDPOINT: WEBHOOK_RESOURCE_KEY}

    def test_webhook_template_is_wired_up(self):
        template = self.source.webhook_template

        # Routing and signature checks are exercised by running the template in
        # test_mailgun_webhook_template.py; this only guards the wiring.
        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert template.id == "template-warehouse-source-mailgun"

    @pytest.mark.parametrize(
        "eligible_schema_names, expected",
        [
            ([WEBHOOK_EVENTS_ENDPOINT], sorted(WEBHOOK_TYPES)),
            (["events"], None),
            ([], None),
        ],
    )
    def test_desired_webhook_events_speak_mailgun_type_ids(self, eligible_schema_names, expected):
        assert self.source.get_desired_webhook_events(self.config, eligible_schema_names) == expected

    @pytest.mark.parametrize(
        "method, patched, return_value",
        [
            ("create_webhook", "create_mailgun_webhook", WebhookCreationResult(success=True)),
            ("delete_webhook", "delete_mailgun_webhook", WebhookDeletionResult(success=True)),
            ("get_external_webhook_info", "get_mailgun_webhook_info", ExternalWebhookInfo(exists=True)),
        ],
    )
    def test_webhook_methods_target_the_configured_account_and_region(self, method, patched, return_value):
        config = MailgunSourceConfig(api_key="key-123", region="eu")

        with mock.patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.{patched}"
        ) as mock_fn:
            mock_fn.return_value = return_value
            result = getattr(self.source, method)(config, WEBHOOK_URL, self.team_id)

        assert result is return_value
        mock_fn.assert_called_once_with("key-123", "eu", WEBHOOK_URL)

    @pytest.mark.parametrize(
        "eligible_schema_names, expect_call",
        [
            ([WEBHOOK_EVENTS_ENDPOINT], True),
            (["events"], False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.source.sync_mailgun_webhook_events"
    )
    def test_sync_only_touches_mailgun_when_the_webhook_table_is_selected(
        self, mock_sync, eligible_schema_names, expect_call
    ):
        mock_sync.return_value = mock.MagicMock(success=True)

        result = self.source.sync_webhook_events(self.config, WEBHOOK_URL, self.team_id, eligible_schema_names)

        assert result.success is True
        assert mock_sync.called is expect_call
