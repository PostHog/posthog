from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.api.trigger import WorkflowStartOutcome
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.scanning import MAX_SESSIONS_PER_SCAN, run_inline_scan, scan_existing_scanner


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


class TestScanEligibility(BaseTest):
    """A session with no replay data can only fail, so no scan may start on one."""

    def _with_replay_data(self, present: set[str]):
        return patch.object(
            SessionReplayEvents,
            "batch_exists",
            side_effect=lambda session_ids, team: {s: s in present for s in session_ids},
        )

    def _start_inline(self, session_ids: list[str]):
        return run_inline_scan(
            team=self.team,
            user=self.user,
            session_ids=session_ids,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )

    @parameterized.expand(["inline", "saved"])
    @pytest.mark.django_db
    def test_a_session_with_no_replay_data_never_starts_a_workflow(self, entry_point: str):
        # The whole point of the pre-flight check: without it the workflow starts, spends a credit, and
        # only then finds there is nothing to watch.
        with (
            self._with_replay_data({"watchable"}),
            patch("products.replay_vision.backend.api.trigger.start_apply_scanner_workflow") as mock_start,
        ):
            mock_start.return_value = (None, WorkflowStartOutcome.STARTED)
            if entry_point == "inline":
                results = self._start_inline(["watchable", "gone"]).results
            else:
                scanner = ReplayScanner.objects.create(
                    team=self.team,
                    name="my-scanner",
                    scanner_type=ScannerType.MONITOR,
                    scanner_config={"prompt": "did the user check out?"},
                    model=ScannerModel.GEMINI_3_7_FLASH,
                )
                _, results = scan_existing_scanner(scanner=scanner, session_ids=["watchable", "gone"], user=self.user)

        # Order matters: the caller reads outcomes back positionally against the batch it sent.
        assert [r["session_id"] for r in results] == ["watchable", "gone"]
        assert results[1]["scan_outcome"] == "no_replay_data"
        assert [call.args[1] for call in mock_start.call_args_list] == ["watchable"]

    @pytest.mark.django_db
    def test_a_batch_with_nothing_watchable_leaves_no_scanner_behind(self):
        # Same rule the used-up-quota path already follows: don't mint a scanner for a question that
        # could never be answered, or every such ask leaves a row behind.
        with self._with_replay_data(set()):
            scan = self._start_inline(["gone-1", "gone-2"])

        assert scan.scanner is None
        assert scan.started == 0
        assert {r["scan_outcome"] for r in scan.results} == {"no_replay_data"}
        assert not ReplayScanner.all_origins.filter(team=self.team).exists()
