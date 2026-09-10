import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import STRIPE_API_VERSION_ACACIA
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import WebhookRepin

pytestmark = [pytest.mark.django_db]

COMMAND = "repin_stripe_webhook_api_version"
DRIFTED_KEY = "sk_test_drifted"


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _create_source_with_webhook(
    team, secret_key: str, auth_method: str = "api_key"
) -> tuple[ExternalDataSource, HogFunction]:
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        source_type="Stripe",
        job_inputs={"stripe_secret_key": secret_key, "auth_method": auth_method},
    )
    hog_function = HogFunction.objects.create(
        team=team,
        type="warehouse_source_webhook",
        name="Stripe warehouse source webhook",
        hog="// test code",
        enabled=True,
        inputs_schema=[
            {"key": "signing_secret", "type": "string", "secret": True},
            {"key": "schema_mapping", "type": "json"},
            {"key": "source_id", "type": "string"},
        ],
        inputs={
            "signing_secret": {"value": "whsec_old"},
            "schema_mapping": {"value": {"invoice": str(uuid.uuid4())}},
            "source_id": {"value": str(source.id)},
        },
    )
    return source, hog_function


def _stored_secret(hog_function_id) -> str | None:
    stored = HogFunction.objects.get(id=hog_function_id)
    return ((stored.encrypted_inputs or {}).get("signing_secret") or {}).get("value")


def _parse_config(job_inputs) -> SimpleNamespace:
    return SimpleNamespace(
        stripe_secret_key=job_inputs["stripe_secret_key"],
        auth_method=SimpleNamespace(selection=job_inputs.get("auth_method", "api_key")),
    )


def _webhook_info(config, webhook_url, team_id, api_version=None) -> ExternalWebhookInfo:
    drifted = config.stripe_secret_key == DRIFTED_KEY
    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        api_version=None if drifted else STRIPE_API_VERSION_ACACIA,
    )


class TestRepinStripeWebhookApiVersion:
    def test_dry_run_does_not_touch_stripe_or_the_signing_secret(self, team):
        _, hog_function = _create_source_with_webhook(team, DRIFTED_KEY)

        with (
            patch.object(StripeSource, "parse_config", side_effect=_parse_config),
            patch.object(StripeSource, "get_external_webhook_info", side_effect=_webhook_info),
            patch.object(StripeSource, "create_pinned_webhook_replacement") as create,
        ):
            call_command(COMMAND)

        create.assert_not_called()
        assert _stored_secret(hog_function.id) == "whsec_old"

    def test_stores_the_new_secret_before_deleting_the_replaced_endpoint(self, team):
        _, drifted_hog_function = _create_source_with_webhook(team, DRIFTED_KEY)
        _, pinned_hog_function = _create_source_with_webhook(team, "sk_test_pinned")

        secret_when_deleted: list[str | None] = []

        def record_secret(config, endpoint_id, team_id) -> WebhookDeletionResult:
            secret_when_deleted.append(_stored_secret(drifted_hog_function.id))
            return WebhookDeletionResult(success=True)

        with (
            patch.object(StripeSource, "parse_config", side_effect=_parse_config),
            patch.object(StripeSource, "get_external_webhook_info", side_effect=_webhook_info),
            patch.object(
                StripeSource,
                "create_pinned_webhook_replacement",
                return_value=WebhookRepin(
                    status="replaced",
                    previous_api_version=None,
                    signing_secret="whsec_new",
                    replaced_endpoint_id="we_old",
                ),
            ) as create,
            patch.object(StripeSource, "delete_webhook_endpoint", side_effect=record_secret),
        ):
            call_command(COMMAND, live_run=True)

        # Stripe delivers to both endpoints until the old one goes, so the new secret has to be
        # stored first. Deleting first would leave every delivery failing the signature check.
        assert secret_when_deleted == ["whsec_new"]
        assert _stored_secret(drifted_hog_function.id) == "whsec_new"
        assert create.call_count == 1
        assert _stored_secret(pinned_hog_function.id) == "whsec_old"

    def test_app_connected_source_is_never_queued_for_replacement(self, team, capsys):
        _create_source_with_webhook(team, DRIFTED_KEY, auth_method="oauth")

        with (
            patch.object(StripeSource, "parse_config", side_effect=_parse_config),
            patch.object(StripeSource, "get_external_webhook_info", side_effect=_webhook_info),
            patch.object(StripeSource, "create_pinned_webhook_replacement") as create,
        ):
            call_command(COMMAND, live_run=True)

        create.assert_not_called()
        assert "Manual fix needed" in capsys.readouterr().out

    def test_a_replacement_without_a_secret_names_the_endpoint_it_left_behind(self, team, capsys):
        _, hog_function = _create_source_with_webhook(team, DRIFTED_KEY)

        with (
            patch.object(StripeSource, "parse_config", side_effect=_parse_config),
            patch.object(StripeSource, "get_external_webhook_info", side_effect=_webhook_info),
            patch.object(
                StripeSource,
                "create_pinned_webhook_replacement",
                return_value=WebhookRepin(
                    status="failed",
                    created_endpoint_id="we_new",
                    error="Stripe returned no signing secret",
                ),
            ),
            patch.object(StripeSource, "delete_webhook_endpoint") as delete,
        ):
            call_command(COMMAND, live_run=True)

        # The endpoint is live in Stripe and its secret is unrecoverable, so the run has to name it.
        assert "we_new" in capsys.readouterr().out
        delete.assert_not_called()
        assert _stored_secret(hog_function.id) == "whsec_old"
