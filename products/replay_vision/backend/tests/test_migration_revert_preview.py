import datetime as dt
import importlib

from posthog.test.base import APIBaseTest

from django.apps import apps
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType

m54 = importlib.import_module("products.replay_vision.backend.migrations.0054_revert_remapped_preview_scanners")

PREVIEW = "gemini-3-flash-preview"
FLASH = "gemini-3.6-flash"
LEGACY_FLASH = "gemini-3.5-flash"

REMAP_AT = dt.datetime(2026, 7, 21, 22, 15, tzinfo=dt.UTC)
BEFORE = REMAP_AT - dt.timedelta(days=2)
AFTER = REMAP_AT + dt.timedelta(days=1)


class TestRevertRemappedPreviewScanners(APIBaseTest):
    def _scanner(self, name: str, model: str, created_at: dt.datetime, version: int = 1) -> ReplayScanner:
        scanner = ReplayScanner.objects.create(
            team=self.team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=model,
            scanner_version=version,
        )
        # created_at is auto_now_add, so override it with a raw UPDATE.
        ReplayScanner.objects.filter(pk=scanner.pk).update(created_at=created_at)
        scanner.refresh_from_db()
        return scanner

    def _observation(self, scanner: ReplayScanner, session_id: str, snap_model: str, snap_version: int) -> None:
        ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            triggered_by=ObservationTrigger.SCHEDULE,
            scanner_snapshot={
                "name": scanner.name,
                "scanner_type": "monitor",
                "scanner_version": snap_version,
                "model": snap_model,
                "provider": "google",
                "emits_signals": False,
                "scanner_config": {"prompt": "p"},
            },
        )

    def test_reverts_pre_remap_36_scanners_except_positively_legacy_flash(self) -> None:
        # Pre-remap, snapshot at current version proves preview: a clear remap victim.
        confident = self._scanner("confident", FLASH, BEFORE, version=2)
        self._observation(confident, "a1", PREVIEW, 2)

        # Pre-remap, no snapshot evidence at current version: uncertain, swept back to preview.
        uncertain = self._scanner("uncertain", FLASH, BEFORE)

        # Pre-remap, snapshot at current version recorded the 15-credit 3.5-flash tier: keep 3.6.
        legacy_flash = self._scanner("legacy_flash", FLASH, BEFORE, version=1)
        self._observation(legacy_flash, "c1", LEGACY_FLASH, 1)

        # Created after the remap, so 0052 never touched it: keep 3.6.
        post_remap = self._scanner("post_remap", FLASH, AFTER)

        # A different model is out of scope entirely.
        untouched = self._scanner("lite", ScannerModel.GEMINI_3_5_FLASH_LITE, BEFORE)

        m54._do_revert(apps, REMAP_AT)

        for scanner in (confident, uncertain, legacy_flash, post_remap, untouched):
            scanner.refresh_from_db()

        assert confident.model == ScannerModel.GEMINI_3_FLASH_PREVIEW
        assert uncertain.model == ScannerModel.GEMINI_3_FLASH_PREVIEW
        assert legacy_flash.model == FLASH
        assert post_remap.model == FLASH
        assert untouched.model == ScannerModel.GEMINI_3_5_FLASH_LITE
