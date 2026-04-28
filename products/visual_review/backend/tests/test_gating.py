"""
Gating invariant tests for visual review.

The CI gate passes iff no "unresolved" changes remain on the run.
A snapshot becomes resolved when quarantined, tolerated, or approved
at the snapshot level.

Each snapshot has two independent axes:

    result:  changed | new | removed | unchanged
    action:  none | quarantine | tolerate | approve

Not all combos are valid (can't tolerate an unchanged snapshot),
yielding 11 valid states. Since snapshots don't influence each other
(the gate is a sum), testing all 11 single-snapshot cases exhaustively
covers the entire state space.
"""

import pytest

from products.visual_review.backend import logic
from products.visual_review.backend.facade.enums import ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import QuarantinedIdentifier, Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

RESULT_ENUM = {
    "changed": SnapshotResult.CHANGED,
    "new": SnapshotResult.NEW,
    "removed": SnapshotResult.REMOVED,
    "unchanged": SnapshotResult.UNCHANGED,
}

# fmt: off
# (result, action, gate_passes, expected_changed_count)
# gate_passes: True when unresolved=0 (action resolves the change or result is unchanged)
# expected_changed_count: raw classifier count on the Run model (excludes quarantined only)
GATE_CASES = [
    pytest.param("unchanged", None,          True,  0, id="unchanged"),
    pytest.param("changed",   None,          False, 1, id="changed-unresolved"),
    pytest.param("changed",   "quarantine",  True,  0, id="changed-quarantined"),
    pytest.param("changed",   "tolerate",    True,  1, id="changed-tolerated"),
    pytest.param("changed",   "approve",     True,  1, id="changed-approved"),
    pytest.param("new",       None,          False, 0, id="new-unresolved"),
    pytest.param("new",       "quarantine",  True,  0, id="new-quarantined"),
    pytest.param("new",       "approve",     True,  0, id="new-approved"),
    pytest.param("removed",   None,          False, 0, id="removed-unresolved"),
    pytest.param("removed",   "quarantine",  True,  0, id="removed-quarantined"),
    pytest.param("removed",   "approve",     True,  0, id="removed-approved"),
]
# fmt: on


@pytest.mark.django_db(transaction=True, databases=PRODUCT_DATABASES)
class TestGatingInvariants:
    @pytest.fixture(autouse=True)
    def _setup(self, team, user, mocker):
        self.team = team
        self.user = user
        self.mocker = mocker
        self.repo = logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test-gating")
        mocker.patch("products.visual_review.backend.logic._post_commit_status")
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")

    def _build_run(self, result: str, action: str | None) -> Run:
        snapshots: list[dict] = []
        baseline: dict[str, str] = {}

        if result == "changed":
            snapshots = [{"identifier": "target", "content_hash": "current_hash"}]
            baseline = {"target": "baseline_hash"}
        elif result == "new":
            snapshots = [{"identifier": "target", "content_hash": "current_hash"}]
        elif result == "removed":
            baseline = {"target": "baseline_hash"}
        elif result == "unchanged":
            snapshots = [{"identifier": "target", "content_hash": "same_hash"}]
            baseline = {"target": "same_hash"}

        self.mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=(baseline, 0),
        )

        run, _ = logic.create_run(
            repo_id=self.repo.id,
            team_id=self.team.id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="feat/test",
            pr_number=1,
            snapshots=snapshots,
        )
        logic.complete_run(run.id)
        run.refresh_from_db()
        if run.status == RunStatus.PROCESSING:
            logic.finish_processing(run.id)
            run.refresh_from_db()

        if action == "quarantine":
            QuarantinedIdentifier.objects.create(
                repo=self.repo,
                team_id=self.team.id,
                identifier="target",
                run_type=RunType.STORYBOOK,
                reason="test",
            )
        elif action == "tolerate":
            snapshot = run.snapshots.get(identifier="target")
            logic.mark_snapshot_as_tolerated(run.id, snapshot.id, self.user.id, self.team.id)
        elif action == "approve":
            snapshot = run.snapshots.get(identifier="target")
            if result == "removed":
                snapshot.review_state = ReviewState.APPROVED
                snapshot.save(update_fields=["review_state"])
            else:
                logic.get_or_create_artifact(
                    repo_id=self.repo.id,
                    content_hash=snapshot.current_hash,
                    storage_path=f"p/{snapshot.current_hash}",
                )
                logic.approve_snapshots(
                    run_id=run.id,
                    user_id=self.user.id,
                    approved_snapshots=[{"identifier": "target", "new_hash": snapshot.current_hash}],
                )

        return run

    @pytest.mark.parametrize("result, action, expected_gate_passes, expected_changed_count", GATE_CASES)
    def test_gate_outcome(self, result, action, expected_gate_passes, expected_changed_count):
        run = self._build_run(result, action)
        recompute_result = logic.recompute_run(run.id, team_id=self.team.id)
        gate_passes = recompute_result["unresolved"] == 0
        assert gate_passes is expected_gate_passes

    @pytest.mark.parametrize("result, action, _expected_gate, expected_changed_count", GATE_CASES)
    def test_raw_counts_reflect_classifier_truth(self, result, action, _expected_gate, expected_changed_count):
        run = self._build_run(result, action)
        logic.recompute_run(run.id, team_id=self.team.id)
        run.refresh_from_db()
        assert run.changed_count == expected_changed_count

    @pytest.mark.parametrize("result, action, _expected_gate, _expected_changed", GATE_CASES)
    def test_result_not_mutated_by_action_or_recompute(self, result, action, _expected_gate, _expected_changed):
        run = self._build_run(result, action)
        logic.recompute_run(run.id, team_id=self.team.id)

        snapshot = run.snapshots.get(identifier="target")
        snapshot.refresh_from_db()
        assert snapshot.result == RESULT_ENUM[result]

    @pytest.mark.parametrize("result, action, _expected_gate, _expected_changed", GATE_CASES)
    def test_recompute_is_idempotent(self, result, action, _expected_gate, _expected_changed):
        run = self._build_run(result, action)
        logic.recompute_run(run.id, team_id=self.team.id)

        second = logic.recompute_run(run.id, team_id=self.team.id)
        assert second["counts_changed"] is False
