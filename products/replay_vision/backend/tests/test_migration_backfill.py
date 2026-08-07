import uuid
import importlib

from posthog.test.base import APIBaseTest

from django.apps import apps
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType

m33 = importlib.import_module("products.replay_vision.backend.migrations.0033_backfill_replayobservationusage_team_id")
m37 = importlib.import_module("products.replay_vision.backend.migrations.0037_backfill_replayobservationusage_credits")
m56 = importlib.import_module("products.replay_vision.backend.migrations.0057_closed_beta_launch_reset")


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
            model=ScannerModel.GEMINI_3_6_FLASH,
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


class TestClosedBetaLaunchReset(APIBaseTest):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_us_disables_scanners_except_internal_and_zeroes_receipts(self) -> None:
        internal_team = (
            self.team
            if self.team.id == m56.INTERNAL_TEAM_ID
            else Team.objects.create(id=m56.INTERNAL_TEAM_ID, organization=self.organization, name="internal")
        )
        beta_team = Team.objects.create(organization=self.organization, name="beta")
        internal_scanner = ReplayScanner.objects.create(
            team=internal_team,
            name="internal",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_6_FLASH,
        )
        beta_scanner = ReplayScanner.objects.create(
            team=beta_team,
            name="beta",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_6_FLASH,
        )
        receipt = ReplayObservationUsage.objects.create(
            observation_id=uuid.uuid4(),
            organization_id=self.organization.id,
            team_id=beta_team.id,
            observation_created_at=timezone.now(),
            model=ScannerModel.GEMINI_3_6_FLASH,
            credits=15,
        )

        m56.reset_closed_beta_state(apps, None)

        internal_scanner.refresh_from_db()
        beta_scanner.refresh_from_db()
        receipt.refresh_from_db()
        assert internal_scanner.enabled
        assert not beta_scanner.enabled
        assert receipt.credits == 0

    @parameterized.expand(
        [
            ("eu_team_2_not_exempt", "EU", False, 0),
            ("self_hosted_untouched", None, True, 15),
        ]
    )
    def test_reset_outside_us(
        self, _name: str, deployment: str | None, expect_enabled: bool, expect_credits: int
    ) -> None:
        team_2 = (
            self.team
            if self.team.id == m56.INTERNAL_TEAM_ID
            else Team.objects.create(id=m56.INTERNAL_TEAM_ID, organization=self.organization, name="two")
        )
        scanner = ReplayScanner.objects.create(
            team=team_2,
            name="s",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_6_FLASH,
        )
        receipt = ReplayObservationUsage.objects.create(
            observation_id=uuid.uuid4(),
            organization_id=self.organization.id,
            team_id=team_2.id,
            observation_created_at=timezone.now(),
            model=ScannerModel.GEMINI_3_6_FLASH,
            credits=15,
        )

        with override_settings(CLOUD_DEPLOYMENT=deployment):
            m56.reset_closed_beta_state(apps, None)

        scanner.refresh_from_db()
        receipt.refresh_from_db()
        assert scanner.enabled is expect_enabled
        assert receipt.credits == expect_credits
