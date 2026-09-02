from posthog.test.base import BaseTest

from products.replay_vision.backend.models import ReplayScanner
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.signals.backend.facade.api import has_enabled_source, onboarding_sources, set_sources


class TestOnboardingSources(BaseTest):
    def _emitting_scanner(self, **overrides) -> ReplayScanner:
        defaults = {
            "team": self.team,
            "name": "my-scanner",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": "test"},
            "model": ScannerModel.GEMINI_3_7_FLASH,
            "enabled": True,
            "emits_signals": True,
        }
        defaults.update(overrides)
        return ReplayScanner.objects.create(**defaults)

    def _source(self, key: str):
        return next(source for source in onboarding_sources(self.team.id) if source.key == key)

    def test_emitting_scanner_alone_counts_as_an_enabled_source(self):
        # Replay Vision writes no SignalSourceConfig row, so a scanner-only team used to read as
        # having nothing on, leaving the Slack onboarding "Sources" step unchecked forever.
        assert has_enabled_source(self.team.id) is False
        self._emitting_scanner()
        assert has_enabled_source(self.team.id) is True

    def test_scanner_not_emitting_or_disabled_does_not_count(self):
        self._emitting_scanner(emits_signals=False)
        self._emitting_scanner(name="off-scanner", enabled=False)
        assert has_enabled_source(self.team.id) is False

    def test_replay_vision_is_reported_but_never_tickable(self):
        replay_vision = self._source("replay_vision")
        assert replay_vision.togglable is False
        assert replay_vision.enabled is False

        self._emitting_scanner()
        assert self._source("replay_vision").enabled is True

    def test_set_sources_leaves_replay_vision_alone(self):
        # It has no config row to write, and submitting the checkbox snapshot without it must not
        # read as "untick Replay Vision".
        self._emitting_scanner()
        set_sources(self.team.id, None, ["error_tracking"])
        assert self._source("replay_vision").enabled is True
