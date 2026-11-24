from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from products.visual_review.backend.facade.contracts import AUTO_EXTEND_BEFORE_EXPIRY_HOURS, AUTO_QUARANTINE_DAYS
from products.visual_review.backend.facade.enums import (
    ActorType,
    AutoQuarantineMode,
    QuarantineLiftState,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import auto_extend, auto_quarantine, repos
from products.visual_review.backend.logic.auto_extend import RecentRenders, extend_reason, should_extend
from products.visual_review.backend.models import QuarantinedIdentifier, QuarantineLiftRequest, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _renders(**overrides) -> RecentRenders:
    fields = {
        "expires_at": _NOW + timedelta(hours=24),
        "default_branch_runs": 100,
        "renders": 100,
        "changed_renders": 1,
        "changed_pictures": 1,
    }
    return RecentRenders(**{**fields, **overrides})


class TestShouldExtend:
    @pytest.mark.parametrize(
        "_name,renders,expected",
        [
            ("extends_on_one_changed_render", _renders(), True),
            (
                "extends_at_the_edge_of_the_window",
                _renders(expires_at=_NOW + timedelta(hours=AUTO_EXTEND_BEFORE_EXPIRY_HOURS)),
                True,
            ),
            ("lets_a_story_without_a_change_lapse", _renders(changed_renders=0, changed_pictures=0), False),
            (
                "waits_while_the_expiry_is_outside_the_window",
                _renders(expires_at=_NOW + timedelta(hours=AUTO_EXTEND_BEFORE_EXPIRY_HOURS, seconds=1)),
                False,
            ),
            ("ignores_a_quarantine_without_expiry", _renders(expires_at=None), False),
            ("ignores_a_quarantine_that_ran_out", _renders(expires_at=_NOW), False),
        ],
    )
    def test_rule(self, _name: str, renders: RecentRenders, expected: bool) -> None:
        assert should_extend(renders, _NOW) is expected


class TestExtendReason:
    @pytest.mark.parametrize(
        "renders,expected",
        [
            (
                _renders(changed_renders=37, changed_pictures=2),
                "Extended automatically: changed in 37 of the last 100 default-branch runs, 2 pictures",
            ),
            (
                _renders(changed_renders=37, changed_pictures=1),
                "Extended automatically: changed in 37 of the last 100 default-branch runs, 1 picture",
            ),
            # Every render changed, but to two pictures: a flake and no stale baseline.
            (
                _renders(changed_renders=100, changed_pictures=2),
                "Extended automatically: changed in 100 of the last 100 default-branch runs, 2 pictures",
            ),
            (
                _renders(renders=60, changed_renders=60, changed_pictures=1),
                "Extended automatically: the same changed picture in all 60 renders of the last 100 "
                "default-branch runs. The baseline looks stale, so approve the new picture instead of waiting",
            ),
        ],
    )
    def test_names_the_evidence_and_a_stale_baseline(self, renders: RecentRenders, expected: str) -> None:
        assert extend_reason(renders) == expected


_IDENTIFIER = "scenes-app-button--primary--light"


@pytest.fixture
def repo(team) -> Repo:
    repo = repos.create_repo(team_id=team.id, repo_external_id=88102, repo_full_name="org/auto-extend")
    repo.auto_quarantine_mode = AutoQuarantineMode.ON
    repo.save()
    return repo


def _run(
    repo: Repo,
    branch: str,
    sha: str,
    result: SnapshotResult,
    *,
    current_hash: str = "",
    baseline_hash: str = "base",
    pr_number: int | None = None,
    hours_ago: int | None = None,
) -> Run:
    run = Run.objects.create(
        team_id=repo.team_id,
        repo=repo,
        run_type=RunType.STORYBOOK,
        branch=branch,
        commit_sha=sha,
        pr_number=pr_number,
        status=RunStatus.COMPLETED,
        purpose=RunPurpose.OBSERVE,
        completed_at=timezone.now(),
    )
    if hours_ago is not None:
        # A run pointing at itself as superseded frees the branch's latest-run slot for the next one.
        Run.objects.filter(id=run.id).update(superseded_by=run, created_at=timezone.now() - timedelta(hours=hours_ago))
    RunSnapshot.objects.create(
        team_id=repo.team_id,
        run=run,
        identifier=_IDENTIFIER,
        result=result,
        baseline_hash=baseline_hash,
        current_hash=current_hash or baseline_hash,
    )
    return run


def _quarantine(repo: Repo, expires_in_hours: int, identifier: str = _IDENTIFIER) -> QuarantinedIdentifier:
    return QuarantinedIdentifier.objects.create(
        team_id=repo.team_id,
        repo=repo,
        identifier=identifier,
        run_type=RunType.STORYBOOK,
        reason="flaky",
        expires_at=timezone.now() + timedelta(hours=expires_in_hours),
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestExtendDifferingQuarantines:
    @pytest.fixture(autouse=True)
    def commit_contains(self):
        with (
            patch("products.visual_review.backend.logic.github_api.default_branch_name", return_value="master"),
            patch("products.visual_review.backend.logic.github_api.default_branch_head_sha", return_value="h" * 40),
            patch(
                "products.visual_review.backend.logic.github_api.commit_contains", return_value=True
            ) as commit_contains,
        ):
            yield commit_contains

    @pytest.fixture
    def captured(self):
        events: list[str] = []
        with patch("products.visual_review.backend.logic.auto_extend.ph_scoped_capture") as scoped:
            scoped.return_value.__enter__.return_value = lambda **kwargs: events.append(kwargs["event"])
            yield events

    @pytest.mark.parametrize(
        "mode,extended,events",
        [(AutoQuarantineMode.OFF, False, 0), (AutoQuarantineMode.PREVIEW, False, 1), (AutoQuarantineMode.ON, True, 1)],
    )
    def test_the_mode_decides_what_a_differing_story_does(self, repo, captured, mode, extended, events):
        repo.auto_quarantine_mode = mode
        repo.save()
        entry = _quarantine(repo, expires_in_hours=24)
        lift_request = QuarantineLiftRequest.objects.create(
            team_id=repo.team_id,
            repo=repo,
            quarantine=entry,
            identifier=_IDENTIFIER,
            run_type=RunType.STORYBOOK,
            pr_number=7,
            expected_hash="fixed",
        )
        _run(repo, "master", "a" * 40, SnapshotResult.CHANGED, current_hash="stale", hours_ago=48)
        _run(repo, "master", "b" * 40, SnapshotResult.CHANGED, current_hash="stale", hours_ago=24)
        finishing = _run(repo, "master", "c" * 40, SnapshotResult.CHANGED, current_hash="stale")

        auto_extend.extend_differing_quarantines(finishing.id)
        if mode == AutoQuarantineMode.PREVIEW:
            auto_extend.extend_differing_quarantines(finishing.id)

        rows = list(QuarantinedIdentifier.objects.filter(identifier=_IDENTIFIER).order_by("created_at"))
        lift_request.refresh_from_db()
        assert captured == ["vr_quarantine_extend"] * events
        if not extended:
            assert [row.id for row in rows] == [entry.id]
            assert rows[0].expires_at == entry.expires_at
            assert lift_request.quarantine_id == entry.id
            return
        old, new = rows
        assert (lift_request.quarantine_id, lift_request.state) == (new.id, QuarantineLiftState.PENDING)
        assert old.expires_at is not None and old.expires_at <= new.created_at
        assert (new.source, new.source_run_id, new.created_by_id) == (ActorType.AUTO, finishing.id, None)
        assert new.reason == (
            "Extended automatically: the same changed picture in all 3 renders of the last 3 default-branch runs. "
            "The baseline looks stale, so approve the new picture instead of waiting"
        )
        assert new.expires_at is not None
        assert abs(new.expires_at - (timezone.now() + timedelta(days=AUTO_QUARANTINE_DAYS))) < timedelta(minutes=1)

    @pytest.mark.parametrize(
        "case",
        [
            "change_only_outside_default_branch_runs",
            "new_is_no_difference",
            "expiry_outside_the_window",
            "changed_picture_approved_since",
            "commit_not_on_default_branch",
        ],
    )
    def test_a_story_without_a_default_branch_change_or_a_distant_expiry_lapses_as_planned(
        self, repo, captured, commit_contains, case
    ):
        commit_contains.return_value = case != "commit_not_on_default_branch"
        entry = _quarantine(repo, expires_in_hours=24 if case != "expiry_outside_the_window" else 72)
        master_result = SnapshotResult.NEW if case == "new_is_no_difference" else SnapshotResult.UNCHANGED
        _run(repo, "master", "a" * 40, master_result, hours_ago=48)
        if case in ("expiry_outside_the_window", "changed_picture_approved_since", "commit_not_on_default_branch"):
            _run(repo, "master", "b" * 40, SnapshotResult.CHANGED, current_hash="flaky", hours_ago=24)
        _run(repo, "trunk-merge/pr-7/abc", "q" * 40, SnapshotResult.CHANGED, current_hash="flaky", hours_ago=12)
        _run(repo, "feature", "p" * 40, SnapshotResult.CHANGED, current_hash="flaky", pr_number=7, hours_ago=6)
        finishing = _run(
            repo,
            "master",
            "c" * 40,
            master_result,
            baseline_hash="flaky" if case == "changed_picture_approved_since" else "base",
        )

        auto_extend.extend_differing_quarantines(finishing.id)

        assert list(QuarantinedIdentifier.objects.filter(identifier=_IDENTIFIER).values_list("id", flat=True)) == [
            entry.id
        ]
        assert captured == []

    def test_the_cap_in_preview_skips_entries_already_reported(self, repo, captured):
        repo.auto_quarantine_mode = AutoQuarantineMode.PREVIEW
        repo.save()
        other = "scenes-app-button--secondary--light"
        _quarantine(repo, expires_in_hours=12)
        _quarantine(repo, expires_in_hours=24, identifier=other)
        finishing = _run(repo, "master", "c" * 40, SnapshotResult.CHANGED, current_hash="flaky")
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=finishing,
            identifier=other,
            result=SnapshotResult.CHANGED,
            baseline_hash="base",
            current_hash="flaky",
        )
        auto_quarantine.first_report(
            "quarantine_extend", repo, RunType.STORYBOOK, _IDENTIFIER, auto_extend._REPORT_SECONDS
        )

        with patch.object(auto_extend, "AUTO_QUARANTINE_MAX_STORIES_PER_RUN", 1):
            auto_extend.extend_differing_quarantines(finishing.id)

        assert captured == ["vr_quarantine_extend"]
