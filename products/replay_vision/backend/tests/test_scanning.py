import datetime as dt
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.queries.scanner_candidate_query import CandidateSession
from products.replay_vision.backend.scanning import (
    MAX_SESSIONS_PER_SCAN,
    STARTER_SCAN_SESSIONS,
    run_inline_scan,
    run_starter_scan,
)


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
                model=ScannerModel.GEMINI_3_7_FLASH,
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
                model=ScannerModel.GEMINI_3_7_FLASH,
            )
        assert not ReplayScanner.all_origins.filter(team=self.team).exists()


class TestStarterScan(BaseTest):
    def _scanner(self) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name="starter",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_7_FLASH,
            sampling_rate=0.25,
        )

    @patch("products.replay_vision.backend.scanning.start_observations", return_value=(2, []))
    @patch("products.replay_vision.backend.scanning.WindowedCandidateQuery")
    def test_scans_the_candidates_it_finds(self, mock_query: MagicMock, mock_start: MagicMock) -> None:
        mock_query.return_value.run.return_value = [
            CandidateSession(session_id="s1", session_end=dt.datetime.now(dt.UTC)),
            CandidateSession(session_id="s2", session_end=dt.datetime.now(dt.UTC)),
        ]
        scanner = self._scanner()
        started = run_starter_scan(scanner=scanner)
        self.assertEqual(started, 2)
        start_kwargs = mock_start.call_args.kwargs
        self.assertEqual(start_kwargs["session_ids"], ["s1", "s2"])
        # Tagged like the sweep: the user asked for a scanner, not for these particular scans.
        self.assertEqual(start_kwargs["trigger"], ObservationTrigger.SCHEDULE)
        self.assertIsNone(start_kwargs["user"])
        query_kwargs = mock_query.call_args.kwargs
        # The starter scan ignores the scanner's sampling: it exists to produce examples now.
        self.assertEqual(query_kwargs["sampling_rate"], 1.0)
        self.assertEqual(query_kwargs["candidate_limit"], STARTER_SCAN_SESSIONS)

    @patch("products.replay_vision.backend.scanning.start_observations")
    @patch("products.replay_vision.backend.scanning.WindowedCandidateQuery")
    def test_starts_nothing_without_candidates(self, mock_query: MagicMock, mock_start: MagicMock) -> None:
        mock_query.return_value.run.return_value = []
        self.assertEqual(run_starter_scan(scanner=self._scanner()), 0)
        mock_start.assert_not_called()
