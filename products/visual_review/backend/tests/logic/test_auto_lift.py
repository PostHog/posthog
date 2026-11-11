from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from products.visual_review.backend.facade.contracts import AUTO_LIFT_CLEAN_DAYS, AUTO_LIFT_MIN_RUNS
from products.visual_review.backend.facade.enums import (
    AutoQuarantineMode,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import auto_lift, repos, runs
from products.visual_review.backend.logic.auto_lift import CleanStreak, is_clean
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
_OLD_ENOUGH = _NOW - timedelta(days=AUTO_LIFT_CLEAN_DAYS, hours=1)


def _streak(**overrides) -> CleanStreak:
    fields = {
        "quarantined_at": _OLD_ENOUGH,
        "window_rows": AUTO_LIFT_MIN_RUNS,
        "unchanged_rows": AUTO_LIFT_MIN_RUNS,
        "finishing_result": SnapshotResult.UNCHANGED,
        "finishing_baseline_hash": "base",
    }
    return CleanStreak(**{**fields, **overrides})


class TestIsClean:
    @pytest.mark.parametrize(
        "_name,streak,expected",
        [
            ("lifts_a_clean_week", _streak(), True),
            (
                "refuses_too_few_runs",
                _streak(window_rows=AUTO_LIFT_MIN_RUNS - 1, unchanged_rows=AUTO_LIFT_MIN_RUNS - 1),
                False,
            ),
            # The unchanged count excludes every other result, so a quarantined or approved change blocks too.
            ("refuses_one_changed_row", _streak(window_rows=AUTO_LIFT_MIN_RUNS + 1), False),
            (
                "refuses_a_young_quarantine",
                _streak(quarantined_at=_NOW - timedelta(days=AUTO_LIFT_CLEAN_DAYS - 1)),
                False,
            ),
            ("refuses_a_finishing_change", _streak(finishing_result=SnapshotResult.CHANGED), False),
            ("refuses_a_finishing_run_without_the_story", _streak(finishing_result=""), False),
            ("refuses_a_finishing_run_without_baseline", _streak(finishing_baseline_hash=""), False),
        ],
    )
    def test_rule(self, _name: str, streak: CleanStreak, expected: bool) -> None:
        assert is_clean(streak, _NOW) is expected


_IDENTIFIER = "scenes-app-button--primary--light"
_FINISHING_SHA = "f" * 40


@pytest.fixture
def repo(team) -> Repo:
    repo = repos.create_repo(team_id=team.id, repo_external_id=88101, repo_full_name="org/auto-lift")
    repo.auto_quarantine_mode = AutoQuarantineMode.ON
    repo.save()
    return repo


def _run(repo: Repo, branch: str, sha: str, result: SnapshotResult, *, finishing: bool = False) -> Run:
    run = Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=RunType.STORYBOOK,
        branch=branch,
        commit_sha=sha,
        status=RunStatus.COMPLETED,
        purpose=RunPurpose.OBSERVE,
        completed_at=timezone.now(),
    )
    if not finishing:
        # A run pointing at itself as superseded frees the branch's latest-run slot for the next one.
        Run.objects.filter(id=run.id).update(superseded_by=run, created_at=timezone.now() - timedelta(days=1))
    RunSnapshot.objects.create(
        team_id=repo.team_id, run=run, identifier=_IDENTIFIER, result=result, baseline_hash="base"
    )
    return run


def _quarantine(repo: Repo) -> QuarantinedIdentifier:
    entry = QuarantinedIdentifier.objects.create(
        team_id=repo.team_id, repo=repo, identifier=_IDENTIFIER, run_type=RunType.STORYBOOK, reason="flaky"
    )
    QuarantinedIdentifier.objects.filter(id=entry.id).update(
        created_at=timezone.now() - timedelta(days=AUTO_LIFT_CLEAN_DAYS + 1)
    )
    return entry


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestReleaseCleanQuarantines:
    @pytest.fixture(autouse=True)
    def github(self):
        # A small minimum keeps the fixture to a handful of runs; the rule itself is covered above.
        with (
            patch("products.visual_review.backend.logic.github_api.default_branch_name", return_value="master"),
            patch("products.visual_review.backend.logic.auto_lift.AUTO_LIFT_MIN_RUNS", 3),
        ):
            yield

    @pytest.fixture
    def capture(self):
        with patch("products.visual_review.backend.logic.auto_lift.ph_scoped_capture") as scoped:
            capture = MagicMock()
            scoped.return_value.__enter__.return_value = capture
            yield capture

    def _week(self, repo: Repo, queue_result: SnapshotResult = SnapshotResult.UNCHANGED) -> Run:
        _run(repo, "master", "a" * 40, SnapshotResult.UNCHANGED)
        _run(repo, "master", "b" * 40, SnapshotResult.UNCHANGED)
        _run(repo, "trunk-merge/pr-7/abc", "c" * 40, queue_result)
        return _run(repo, "master", _FINISHING_SHA, SnapshotResult.UNCHANGED, finishing=True)

    @pytest.mark.parametrize(
        "mode,lifted,events",
        [(AutoQuarantineMode.OFF, False, 0), (AutoQuarantineMode.PREVIEW, False, 1), (AutoQuarantineMode.ON, True, 1)],
    )
    def test_the_mode_decides_what_a_clean_week_does(self, repo, capture, mode, lifted, events):
        repo.auto_quarantine_mode = mode
        repo.save()
        entry = _quarantine(repo)
        finishing = self._week(repo)

        auto_lift.release_clean_quarantines(finishing.id)
        if mode == AutoQuarantineMode.PREVIEW:
            auto_lift.release_clean_quarantines(finishing.id)

        entry.refresh_from_db()
        assert (entry.expires_at is not None) is lifted
        assert capture.call_count == events
        if lifted:
            assert (entry.lifted_at_sha, entry.lift_reason) == (
                _FINISHING_SHA,
                f"Lifted automatically: unchanged in 4 runs over {AUTO_LIFT_CLEAN_DAYS} days",
            )

    def test_one_change_in_a_queue_run_keeps_the_quarantine(self, repo, capture):
        entry = _quarantine(repo)
        finishing = self._week(repo, queue_result=SnapshotResult.CHANGED)

        auto_lift.release_clean_quarantines(finishing.id)

        entry.refresh_from_db()
        assert entry.expires_at is None
        assert capture.call_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestEnqueueCleanQuarantineRelease:
    @pytest.mark.parametrize(
        "branch,pr_number,is_partial,mode,expected_calls",
        [
            ("master", None, False, AutoQuarantineMode.ON, 1),
            ("master", None, False, AutoQuarantineMode.OFF, 0),
            ("master", None, True, AutoQuarantineMode.ON, 0),
            ("feature", 12, False, AutoQuarantineMode.ON, 0),
            ("trunk-merge/pr-7/abc", None, False, AutoQuarantineMode.ON, 0),
        ],
    )
    def test_only_a_full_default_branch_run_queues_the_check_once_an_hour(
        self, repo, branch, pr_number, is_partial, mode, expected_calls
    ):
        repo.auto_quarantine_mode = mode
        repo.save()
        first = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch=branch,
            commit_sha="a" * 40,
            pr_number=pr_number,
            is_partial=is_partial,
            status=RunStatus.COMPLETED,
        )
        Run.objects.filter(id=first.id).update(superseded_by=first)
        second = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch=branch,
            commit_sha="b" * 40,
            pr_number=pr_number,
            is_partial=is_partial,
            status=RunStatus.COMPLETED,
        )

        with patch("products.visual_review.backend.tasks.tasks.release_clean_quarantines.delay") as delay:
            runs._enqueue_clean_quarantine_release(Run.objects.get(id=first.id))
            runs._enqueue_clean_quarantine_release(second)

        assert delay.call_count == expected_calls
