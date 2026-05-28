"""Tests for the LLM-backed agent reviewer."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from products.visual_review.backend import agent_reviewer, agent_signals
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.enums import ChangeKind, ReviewState, RunStatus, SnapshotResult
from products.visual_review.backend.models import Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


class TestSelectSignals:
    def _signals(self, count, diff_pct_start=1.0):
        return [
            agent_signals.SnapshotSignals(
                identifier=f"story-{i}",
                result="changed",
                diff_percentage=diff_pct_start + i,
                ssim_score=None,
                change_kind="pixel",
                size_mismatch=False,
                cluster_count=1,
                largest_cluster_area=100,
                image_area=10_000,
                is_quarantined=False,
            )
            for i in range(count)
        ]

    def test_under_cap_keeps_all(self):
        signals = self._signals(10)
        kept, dropped = agent_reviewer._select_signals(signals)
        assert len(kept) == 10
        assert dropped == 0

    def test_over_cap_drops_smallest_diffs_first(self):
        signals = self._signals(agent_reviewer.MAX_SNAPSHOTS_PER_CALL + 5)
        kept, dropped = agent_reviewer._select_signals(signals)
        assert len(kept) == agent_reviewer.MAX_SNAPSHOTS_PER_CALL
        assert dropped == 5
        # Kept set should be the highest-diff entries — the lowest-diff
        # ones (identifiers story-0..4) should have been dropped.
        kept_identifiers = {s.identifier for s in kept}
        assert "story-0" not in kept_identifiers


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestGenerateAgentReviewFacade:
    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=42, repo_full_name="org/agent-review")

    def _make_run(self, repo, team, status=RunStatus.COMPLETED, **kwargs):
        return Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type="storybook",
            branch="feature",
            commit_sha="sha1",
            status=status,
            **kwargs,
        )

    def _mock_llm_output(self, snapshots: list[tuple[str, str]], run_verdict: str = "approved"):
        """Build a stub RunReviewOutput with one entry per (identifier, verdict)."""
        return agent_reviewer.RunReviewOutput(
            run_verdict=run_verdict,
            run_confidence=0.8,
            run_summary=f"Reviewed {len(snapshots)} snapshot(s)",
            snapshots=[
                agent_reviewer.SnapshotVerdictOutput(
                    identifier=identifier,
                    verdict=verdict,
                    confidence=0.85,
                    reasoning=f"verdict for {identifier}",
                )
                for identifier, verdict in snapshots
            ],
        )

    def test_requires_completed_run(self, repo, team, user):
        run = self._make_run(repo, team, status=RunStatus.PROCESSING)
        with pytest.raises(ValueError, match="must be completed"):
            api.generate_agent_review(run.id, team_id=team.id, user=user)

    @patch("products.visual_review.backend.agent_reviewer.review_run")
    def test_writes_verdict_to_snapshot_and_run_metadata(self, mock_review, repo, team, user):
        run = self._make_run(repo, team)
        # One focused pixel diff that should come back approved
        RunSnapshot.objects.create(
            run=run,
            team_id=team.id,
            identifier="button--primary",
            current_hash="h1",
            baseline_hash="h0",
            result=SnapshotResult.CHANGED,
            review_state=ReviewState.PENDING,
            change_kind=ChangeKind.PIXEL,
            diff_percentage=1.0,
            diff_metadata={
                "cluster_summary": {
                    "items": [{"bbox": [10, 10, 50, 50], "px": 200, "centroid": [35.0, 35.0]}],
                    "total": 1,
                    "truncated": False,
                }
            },
        )
        # Unchanged snapshot — must be skipped
        RunSnapshot.objects.create(
            run=run,
            team_id=team.id,
            identifier="card--default",
            current_hash="h2",
            baseline_hash="h2",
            result=SnapshotResult.UNCHANGED,
        )
        mock_review.return_value = self._mock_llm_output([("button--primary", "approved")])

        result = api.generate_agent_review(run.id, team_id=team.id, user=user)

        # LLM was actually invoked with the changed snapshot only
        assert mock_review.call_count == 1
        call_kwargs = mock_review.call_args.kwargs
        signal_identifiers = [s.identifier for s in call_kwargs["signals"]]
        assert signal_identifiers == ["button--primary"]

        assert result.agent_review is not None
        assert result.agent_review.snapshot_count == 1
        assert result.agent_review.agent == agent_reviewer.MODEL_NAME

        snapshots = api.get_run_snapshots(run.id, team_id=team.id)
        by_identifier = {s.identifier: s for s in snapshots}
        # The changed snapshot got a verdict; the unchanged one did not.
        assert by_identifier["button--primary"].agent_review is not None
        assert by_identifier["button--primary"].agent_review.verdict == "approved"
        assert by_identifier["card--default"].agent_review is None

    @patch("products.visual_review.backend.agent_reviewer.review_run")
    def test_records_deferred_for_snapshots_the_model_skipped(self, mock_review, repo, team, user):
        """If the model omits an identifier we sent, record a defensive deferred verdict."""
        run = self._make_run(repo, team)
        for identifier in ("a", "b"):
            RunSnapshot.objects.create(
                run=run,
                team_id=team.id,
                identifier=identifier,
                current_hash=f"h-{identifier}",
                baseline_hash="h0",
                result=SnapshotResult.CHANGED,
                review_state=ReviewState.PENDING,
                change_kind=ChangeKind.PIXEL,
                diff_percentage=0.5,
            )
        # LLM only emits a verdict for "a"; "b" should get a defensive deferred.
        mock_review.return_value = self._mock_llm_output([("a", "approved")])

        api.generate_agent_review(run.id, team_id=team.id, user=user)

        snapshots = api.get_run_snapshots(run.id, team_id=team.id)
        by_identifier = {s.identifier: s for s in snapshots}
        review_a = by_identifier["a"].agent_review
        review_b = by_identifier["b"].agent_review
        assert review_a is not None
        assert review_b is not None
        assert review_a.verdict == "approved"
        assert review_b.verdict == "deferred"

    @patch("products.visual_review.backend.agent_reviewer.review_run")
    def test_skips_llm_call_when_no_actionable_snapshots(self, mock_review, repo, team, user):
        run = self._make_run(repo, team)
        RunSnapshot.objects.create(
            run=run,
            team_id=team.id,
            identifier="unchanged",
            current_hash="h",
            baseline_hash="h",
            result=SnapshotResult.UNCHANGED,
        )

        result = api.generate_agent_review(run.id, team_id=team.id, user=user)

        assert mock_review.call_count == 0
        assert result.agent_review is not None
        assert result.agent_review.snapshot_count == 0
        assert result.agent_review.verdict == "approved"

    @patch("products.visual_review.backend.agent_reviewer.review_run")
    def test_is_idempotent(self, mock_review, repo, team, user):
        run = self._make_run(repo, team)
        RunSnapshot.objects.create(
            run=run,
            team_id=team.id,
            identifier="story--default",
            current_hash="h1",
            baseline_hash="h0",
            result=SnapshotResult.CHANGED,
            review_state=ReviewState.PENDING,
            change_kind=ChangeKind.PIXEL,
            diff_percentage=0.5,
        )
        mock_review.return_value = self._mock_llm_output([("story--default", "approved")])

        first = api.generate_agent_review(run.id, team_id=team.id, user=user)
        second = api.generate_agent_review(run.id, team_id=team.id, user=user)

        assert first.agent_review is not None
        assert second.agent_review is not None
        assert first.agent_review.verdict == second.agent_review.verdict
        run.refresh_from_db()
        assert isinstance(run.metadata["agent_review"], dict)
        snapshot = RunSnapshot.objects.get(run=run, identifier="story--default")
        assert isinstance(snapshot.metadata["agent_review"], dict)

    @patch("products.visual_review.backend.agent_reviewer.review_run")
    def test_strips_agent_review_from_loose_metadata_field(self, mock_review, repo, team, user):
        """The agent_review entry must be exposed as the typed field only,
        not also duplicated inside the loose `metadata` dict on the wire."""
        run = self._make_run(repo, team, metadata={"pr_title": "Add button"})
        RunSnapshot.objects.create(
            run=run,
            team_id=team.id,
            identifier="story",
            current_hash="h1",
            baseline_hash="h0",
            result=SnapshotResult.CHANGED,
            change_kind=ChangeKind.PIXEL,
            diff_percentage=0.3,
            metadata={"browser": "chrome"},
        )
        mock_review.return_value = self._mock_llm_output([("story", "approved")])

        result = api.generate_agent_review(run.id, team_id=team.id, user=user)

        # Run-level: pr_title preserved, agent_review surfaced as typed field
        assert result.metadata == {"pr_title": "Add button"}
        assert result.agent_review is not None

        snapshots = api.get_run_snapshots(run.id, team_id=team.id)
        snapshot_dto = snapshots[0]
        assert snapshot_dto.metadata == {"browser": "chrome"}
        assert snapshot_dto.agent_review is not None
