from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.cdp.validation import compile_hog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailerlite import (
    MailerLiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import (
    MAILERLITE_V1,
    MAILERLITE_V2,
    SUBSCRIBER_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source import MailerLiteSource


def _config() -> MailerLiteSourceConfig:
    return MailerLiteSourceConfig(api_key="test-key")


class TestMailerLiteSourceClass:
    @pytest.mark.parametrize(
        ("valid", "expected_ok"),
        [(True, True), (False, False)],
    )
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.validate_mailerlite_credentials",
            return_value=valid,
        ):
            ok, error = MailerLiteSource().validate_credentials(_config(), team_id=1)
            assert ok is expected_ok
            assert (error is None) is expected_ok

    def test_validate_credentials_uses_schema_path(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.validate_mailerlite_credentials",
            return_value=True,
        ) as mock_validate:
            MailerLiteSource().validate_credentials(_config(), team_id=1, schema_name="groups")
            assert mock_validate.call_args.args == ("test-key", "/groups")

    def test_default_version_is_v2(self) -> None:
        source = MailerLiteSource()
        assert source.default_version == MAILERLITE_V2
        assert set(source.supported_versions) == {MAILERLITE_V1, MAILERLITE_V2}
        assert source.default_version in source.supported_versions

    def test_v1_is_deprecated_without_sunset(self) -> None:
        # Guards the in-product deprecation banner: v1 must stay flagged, and with no announced
        # sunset date (a fabricated one would flip the framework into "sunsetting" behaviour and
        # invite a repin off a version MailerLite still serves).
        source = MailerLiteSource()
        deprecation = source.get_version_deprecation(MAILERLITE_V1)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert source.get_version_deprecation(MAILERLITE_V2) is None

    @pytest.mark.parametrize(
        ("pin", "expected_version"),
        [(None, MAILERLITE_V2), (MAILERLITE_V1, MAILERLITE_V1), (MAILERLITE_V2, MAILERLITE_V2)],
    )
    def test_source_for_pipeline_plumbing(self, pin: str | None, expected_version: str) -> None:
        inputs = MagicMock(spec=SourceInputs)
        inputs.schema_name = "subscribers"
        inputs.logger = MagicMock()
        inputs.api_version = pin
        inputs.team_id = 7
        inputs.job_id = "job-1"
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source.mailerlite_source"
        ) as mock_source:
            MailerLiteSource().source_for_pipeline(_config(), manager, inputs)
            kwargs = mock_source.call_args.kwargs
            assert kwargs["api_key"] == "test-key"
            assert kwargs["endpoint"] == "subscribers"
            assert kwargs["team_id"] == 7
            assert kwargs["job_id"] == "job-1"
            assert kwargs["resumable_source_manager"] is manager
            assert kwargs["api_version"] == expected_version
            # Without the webhook manager a sync silently ignores every pushed row.
            assert isinstance(kwargs["webhook_source_manager"], WebhookSourceManager)


class TestMailerLiteWebhooks:
    def test_only_subscribers_supports_webhooks(self) -> None:
        # Enabling webhooks on a schema makes the poll skip once the initial sync completes, so a
        # table whose events carry a partial object (campaigns) must stay poll-only.
        schemas = {s.name: s for s in MailerLiteSource().get_schemas(_config(), team_id=1)}
        assert {name for name, s in schemas.items() if s.supports_webhooks} == {"subscribers"}
        assert all(s.webhook_only is False for s in schemas.values())

    def test_webhook_resource_map_matches_event_name_prefix(self) -> None:
        # The hog template routes on the part of the event name before the dot, so the map's value
        # must equal that prefix or every delivery is dropped as unmapped.
        source = MailerLiteSource()
        assert source.webhook_resource_map == {"subscribers": "subscriber"}
        assert set(source.webhook_resource_map) == set(WEBHOOK_SCHEMA_NAMES)
        assert {event.split(".")[0] for event in SUBSCRIBER_WEBHOOK_EVENTS} == {"subscriber"}

    def test_webhook_template_verifies_the_signature(self) -> None:
        template = MailerLiteSource().webhook_template
        assert template is not None
        assert template.type == "warehouse_source_webhook"
        # Deliveries are only trustworthy because of this check; losing it would leave a public
        # ingest endpoint anyone could post to.
        assert "sha256HmacChainHex" in template.code
        assert "request.headers['signature']" in template.code
        assert {i["key"] for i in template.inputs_schema} >= {"signing_secret", "schema_mapping", "source_id"}

    def test_webhook_template_hog_compiles(self) -> None:
        # The template is only compiled when a delivery arrives, so a syntax error here ships a
        # webhook endpoint that fails on every push with nothing to catch it earlier.
        template = MailerLiteSource().webhook_template
        assert template is not None
        assert compile_hog(template.code, template.type)[0] == "_H"

    @pytest.mark.parametrize(
        ("eligible", "expected"),
        [
            (["subscribers"], sorted(SUBSCRIBER_WEBHOOK_EVENTS)),
            (["campaigns", "groups"], []),
            (["subscribers", "campaigns"], sorted(SUBSCRIBER_WEBHOOK_EVENTS)),
        ],
    )
    def test_desired_webhook_events_cover_only_webhook_schemas(self, eligible: list[str], expected: list[str]) -> None:
        assert MailerLiteSource().get_desired_webhook_events(_config(), eligible) == expected

    @pytest.mark.parametrize(
        ("method", "client_function", "expected"),
        [
            ("create_webhook", "create_webhook", WebhookCreationResult(success=True)),
            ("delete_webhook", "delete_webhook", WebhookDeletionResult(success=True)),
            ("get_external_webhook_info", "get_external_webhook_info", ExternalWebhookInfo(exists=True)),
        ],
    )
    def test_webhook_management_reaches_the_api_client(self, method: str, client_function: str, expected: Any) -> None:
        # Unwired, these fall through to the base class, which raises or reports "not supported"
        # and leaves the user with no webhook at all.
        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.{client_function}",
            return_value=expected,
        ) as mock_client:
            result = getattr(MailerLiteSource(), method)(_config(), "https://ph.example/webhook", 1)

        assert result == expected
        assert mock_client.call_args.args == ("test-key", "https://ph.example/webhook")

    def test_sync_webhook_events_sends_the_eligible_events(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.sync_webhook_events",
            return_value=WebhookSyncResult(success=True),
        ) as mock_sync:
            MailerLiteSource().sync_webhook_events(_config(), "https://ph.example/webhook", 1, ["subscribers"])

        assert mock_sync.call_args.args == ("test-key", "https://ph.example/webhook", sorted(SUBSCRIBER_WEBHOOK_EVENTS))
