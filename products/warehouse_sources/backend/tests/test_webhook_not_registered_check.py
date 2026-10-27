import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.health_checks.webhook_not_registered import WebhookNotRegisteredCheck


class TestWebhookNotRegisteredCheck(BaseTest):
    @parameterized.expand(
        [
            ("no_webhook_function", None, True, True),
            ("disabled_webhook_function", False, True, True),
            ("enabled_webhook_function", True, True, False),
            ("initial_sync_not_complete", None, False, False),
        ]
    )
    def test_flags_webhook_schemas_without_an_enabled_webhook(
        self, _name: str, webhook_enabled: bool | None, initial_sync_complete: bool, flagged: bool
    ) -> None:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            team=self.team,
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "sk_test_x"},
        )
        if webhook_enabled is not None:
            HogFunction.objects.create(
                team=self.team,
                type="warehouse_source_webhook",
                hog="return event",
                enabled=webhook_enabled,
                inputs_schema=[{"key": "source_id", "type": "string"}],
                inputs={"source_id": {"value": str(source.pk)}},
            )
        ExternalDataSchema.objects.create(
            name="Customer",
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            should_sync=True,
            initial_sync_complete=initial_sync_complete,
        )

        issues = WebhookNotRegisteredCheck().detect([self.team.id])
        payloads = [result.payload for result in issues.get(self.team.id, [])]

        if flagged:
            assert len(payloads) == 1
            assert payloads[0]["pipeline_id"] == str(source.pk)
            assert payloads[0]["affected_schemas"] == ["Customer"]
        else:
            assert payloads == []
