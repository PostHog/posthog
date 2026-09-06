from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN, run_inline_scan, session_has_replay_data


class TestInlineScanServiceBounds(BaseTest):
    """The service is reachable without DRF, so its own edge has to hold the bounds."""

    def _config(self, **overrides: Any) -> dict[str, Any]:
        config: dict[str, Any] = {"prompt": "did the user check out?"}
        config.update(overrides)
        return config

    @pytest.mark.django_db
    def test_rejects_a_config_the_api_would_reject(self):
        # The config is persisted on the scanner and copied into every observation snapshot, so a
        # caller that skips the serializer must not be able to write one the workflow can't run.
        with pytest.raises(ValueError):
            run_inline_scan(
                team=self.team,
                user=self.user,
                session_ids=["s1"],
                scanner_type=ScannerType.CLASSIFIER,
                scanner_config=self._config(),
                model=ScannerModel.GEMINI_3_8_FLASH,
            )
        assert not ReplayScanner.all_origins.filter(team=self.team).exists()

    @pytest.mark.django_db
    def test_rejects_a_batch_over_the_cap(self):
        # Otherwise a non-API caller starts an unbounded number of workflows.
        with pytest.raises(ValueError):
            run_inline_scan(
                team=self.team,
                user=self.user,
                session_ids=[f"s{i}" for i in range(MAX_SESSIONS_PER_SCAN + 1)],
                scanner_type=ScannerType.MONITOR,
                scanner_config=self._config(),
                model=ScannerModel.GEMINI_3_8_FLASH,
            )
        assert not ReplayScanner.all_origins.filter(team=self.team).exists()


class TestSessionHasReplayData(BaseTest):
    @pytest.mark.django_db
    def test_a_lookup_error_lets_the_scan_through(self):
        # The activity checks eligibility again, so a ClickHouse blip should cost a wasted credit
        # rather than refuse every scan the project asks for.
        with patch("products.replay_vision.backend.scanning.SessionReplayEvents.exists", side_effect=Exception("boom")):
            assert session_has_replay_data(team=self.team, session_id="s1") is True
