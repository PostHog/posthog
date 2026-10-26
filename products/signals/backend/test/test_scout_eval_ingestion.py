from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import override_settings

from products.cdp.backend.facade.models import HogFunction
from products.posthog_ai.eval_harness.environment.ingestion import EnvironmentIngestion
from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt
from products.signals.backend.scout_harness.eval_environment.ingestion import ScoutEnvironmentIngestion


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None)
class TestScoutEnvironmentIngestion(BaseTest):
    def test_prepare_labels_the_verified_guard_without_changing_its_behavior_or_receipt(self) -> None:
        protection = EnvironmentIngestion.install(self.team, self.user)
        receipt = EnvironmentReceipt(
            phase="complete",
            manifest_sha256="0" * 64,
            environment_id="example-environment",
            source_cutoff=datetime(2030, 1, 1, tzinfo=UTC),
            target_cutoff=datetime(2030, 2, 1, tzinfo=UTC),
            timezone="UTC",
            databases={},
            identity_namespace=uuid4(),
            provenance={},
            team_id=self.team.id,
            event_ingestion=protection,
        )
        original_receipt = receipt.model_dump_json()
        original_behavior = protection.model_dump()
        with self.assertRaisesRegex(ValueError, "policy labels changed"):
            ScoutEnvironmentIngestion.verify(receipt)

        ScoutEnvironmentIngestion.prepare(receipt)
        ScoutEnvironmentIngestion.verify(receipt)

        function = HogFunction.objects.get(id=protection.id, team_id=self.team.id)
        assert function.name == "Event ingestion policy"
        assert function.description == "Ignore incoming events for this project."
        assert receipt.model_dump_json() == original_receipt
        assert protection.model_dump() == original_behavior
        protection.verify(self.team)

        HogFunction.objects.filter(id=protection.id, team_id=self.team.id).update(
            name="Changed label", bytecode=["invalid bytecode"]
        )
        with self.assertRaisesRegex(ValueError, "event-ingestion protection is missing or changed"):
            ScoutEnvironmentIngestion.prepare(receipt)
        function.refresh_from_db()
        assert function.name == "Changed label"
