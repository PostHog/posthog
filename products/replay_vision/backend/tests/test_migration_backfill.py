import uuid
import importlib

from posthog.test.base import APIBaseTest

from django.apps import apps
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType

m33 = importlib.import_module("products.replay_vision.backend.migrations.0033_backfill_replayobservationusage_team_id")
m37 = importlib.import_module("products.replay_vision.backend.migrations.0037_backfill_replayobservationusage_credits")


class TestReceiptBackfillMigrations(APIBaseTest):
    def test_backfills_team_model_and_credits_and_survives_orphans(self) -> None:
        # A retired beta model (KeyTextTransform must extract it unquoted so it matches the credit map),
        # plus an orphaned receipt whose observation was deleted (subquery -> NULL): the keyset loop must
        # not spin on it, and it must land on the baseline credits.
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name="s",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        obs = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id="s1",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot={
                "model": "gemini-3.1-flash-lite-preview",
                "name": "s",
                "scanner_type": "monitor",
                "scanner_version": 1,
                "provider": "google",
                "emits_signals": False,
                "scanner_config": {},
            },
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )
        live = ReplayObservationUsage.objects.create(
            observation_id=obs.id,
            organization_id=self.organization.id,
            observation_created_at=timezone.now(),
        )
        orphan = ReplayObservationUsage.objects.create(
            observation_id=uuid.uuid4(),
            organization_id=self.organization.id,
            observation_created_at=timezone.now(),
        )

        m33.backfill_team_id(apps, None)
        m37.backfill_model_and_credits(apps, None)

        live.refresh_from_db()
        orphan.refresh_from_db()
        assert (live.team_id, live.model, live.credits) == (self.team.id, "gemini-3.1-flash-lite-preview", 2)
        assert (orphan.team_id, orphan.model, orphan.credits) == (None, None, 5)
