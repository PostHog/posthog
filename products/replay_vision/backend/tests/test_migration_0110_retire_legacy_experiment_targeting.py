from datetime import timedelta
from typing import Any

from posthog.test.base import TestMigrations

from django.utils import timezone

PROMPT_CONFIG = {"prompt": "Summarize the checkout.", "length": "short"}


class TestRetireLegacyExperimentTargeting(TestMigrations):
    app = "replay_vision"
    migrate_from = "0109_alter_replayobservation_error_reason"
    migrate_to = "0110_retire_legacy_experiment_targeting"

    def setUpBeforeMigration(self, apps: Any) -> None:
        ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
        ReplayScannerBackfill = apps.get_model("replay_vision", "ReplayScannerBackfill")
        ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")

        def scanner(name: str, scanner_type: str, config: dict, targeting: dict | None) -> Any:
            return ReplayScanner.objects.create(
                team_id=self.team.id,
                name=name,
                scanner_type=scanner_type,
                scanner_config=config,
                model="gemini-3.5-flash-lite",
                enabled=True,
                experiment_targeting=targeting,
            )

        def observation(owner: Any, session_id: str, snapshot: dict) -> Any:
            return ReplayObservation.objects.create(
                team_id=self.team.id, scanner=owner, session_id=session_id, scanner_snapshot=snapshot
            )

        def backfill(owner: Any, status: str) -> Any:
            now = timezone.now()
            return ReplayScannerBackfill.objects.create(
                team_id=self.team.id,
                scanner=owner,
                window_start=now - timedelta(days=7),
                window_end=now,
                status=status,
                scanner_snapshot={},
                credits_per_observation=1,
                total_count=0,
            )

        self.one_variant = scanner("one variant", "summarizer", PROMPT_CONFIG, {"experiment_id": 7, "variant": "test"})
        self.every_variant = scanner("every variant", "monitor", {"prompt": "Did it fail?"}, {"experiment_id": 8})
        self.untargeted = scanner("untargeted", "summarizer", PROMPT_CONFIG, None)
        experiment_config = {"prompt": "Compare.", "experiment_id": 9, "variants": None}
        self.experiment = scanner("experiment", "experiment", experiment_config, None)

        self.running = backfill(self.one_variant, "running")
        self.quota_paused = backfill(self.every_variant, "paused_quota")
        self.completed = backfill(self.one_variant, "completed")
        self.untargeted_running = backfill(self.untargeted, "running")

        self.legacy_snapshot = {
            "scanner_type": "summarizer",
            "scanner_config": PROMPT_CONFIG,
            "experiment_targeting": {"experiment_id": 7, "variant": "test"},
        }
        self.legacy_observation = observation(self.one_variant, "s1", self.legacy_snapshot)
        self.experiment_snapshot = {"scanner_type": "experiment", "scanner_config": experiment_config}
        self.experiment_observation = observation(self.experiment, "s2", self.experiment_snapshot)

    def test_retires_legacy_targeted_scanners_and_carries_their_scope_into_config(self) -> None:
        ReplayScanner = self.apps.get_model("replay_vision", "ReplayScanner")  # type: ignore[union-attr]
        ReplayScannerBackfill = self.apps.get_model("replay_vision", "ReplayScannerBackfill")  # type: ignore[union-attr]
        ReplayObservation = self.apps.get_model("replay_vision", "ReplayObservation")  # type: ignore[union-attr]

        one_variant = ReplayScanner.objects.get(pk=self.one_variant.pk)
        every_variant = ReplayScanner.objects.get(pk=self.every_variant.pk)
        assert (one_variant.enabled, every_variant.enabled) == (False, False)
        assert one_variant.scanner_config == {**PROMPT_CONFIG, "experiment_id": 7, "variants": ["test"]}
        assert every_variant.scanner_config == {"prompt": "Did it fail?", "experiment_id": 8, "variants": None}
        assert one_variant.experiment_targeting == {"experiment_id": 7, "variant": "test"}
        assert one_variant.scanner_version == self.one_variant.scanner_version

        statuses = dict(
            ReplayScannerBackfill.objects.filter(
                pk__in=[self.running.pk, self.quota_paused.pk, self.completed.pk, self.untargeted_running.pk]
            ).values_list("pk", "status")
        )
        assert statuses == {
            self.running.pk: "cancelled",
            self.quota_paused.pk: "cancelled",
            self.completed.pk: "completed",
            self.untargeted_running.pk: "running",
        }
        assert ReplayScannerBackfill.objects.get(pk=self.running.pk).finished_at is not None

        assert ReplayScanner.objects.get(pk=self.untargeted.pk).enabled
        assert ReplayScanner.objects.get(pk=self.experiment.pk).enabled

        legacy = ReplayObservation.objects.get(pk=self.legacy_observation.pk).scanner_snapshot
        assert legacy == {
            **self.legacy_snapshot,
            "scanner_config": {**PROMPT_CONFIG, "experiment_id": 7, "variants": ["test"]},
        }
        assert ReplayObservation.objects.get(pk=self.experiment_observation.pk).scanner_snapshot == (
            self.experiment_snapshot
        )
