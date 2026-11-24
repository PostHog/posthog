import pytest

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import BaselineApprovalState, BaselineMode, RunPurpose, RunType
from products.visual_review.backend.logic import approvals, gating, ledger, ledger_advance
from products.visual_review.backend.logic.baseline_record import record_for_run
from products.visual_review.backend.models import BaselineApproval, QuarantinedIdentifier, Repo, Run, ToleratedHash
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import (
    DEFAULT_BRANCH,
    SEED,
    FakeGit,
    LedgerFlow,
    approve,
    seeded_repo,
)

RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
GREEN = (0, 255, 0, 255)
GREY = (128, 128, 128, 255)
YELLOW = (255, 255, 0, 255)
CYAN = (0, 255, 255, 255)
MAGENTA = (255, 0, 255, 255)


@pytest.fixture
def repo(team) -> Repo:
    return seeded_repo(team.id, BaselineMode.LEDGER)


@pytest.fixture
def git(mocker) -> FakeGit:
    return FakeGit(mocker, SEED)


@pytest.fixture
def flow(repo, mocker) -> LedgerFlow:
    flow = LedgerFlow(repo, mocker)
    flow.picture("b0", RED)
    flow.picture("b1", BLUE)
    flow.picture("b2", GREEN)
    flow.picture("c0", GREY)
    flow.picture("g1", YELLOW)
    flow.picture("b9", CYAN)
    flow.picture("t1", MAGENTA)
    return flow


@pytest.fixture
def finalize(user, django_capture_on_commit_callbacks):
    def finalize(run: Run) -> None:
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

    return finalize


def _ledger(repo: Repo) -> dict[str, str]:
    head = ledger.cursor(repo.id)
    assert head is not None
    return ledger.ledger_at(repo.id, RunType.STORYBOOK, head.position)


def _approvals(repo: Repo) -> list[tuple[int, str, str, str, str, str]]:
    return list(
        BaselineApproval.objects.filter(repo=repo)
        .order_by("pr_number", "approved_at")
        .values_list("pr_number", "content_hash", "ledger_base_hash", "effective_base_hash", "state", "evidence")
    )


def _drift(run: Run) -> tuple[int, int, int]:
    return run.changed_count, run.new_count, run.removed_count


def _last_status(flow: LedgerFlow, commit_sha: str) -> tuple[str, str]:
    posts = [call.kwargs for call in flow.statuses.call_args_list if call.args[1] == commit_sha]
    return posts[-1]["state"], posts[-1]["description"]


def _queue_run(flow: LedgerFlow, git: FakeGit, sha: str, pr_head: str, renders: dict[str, str]) -> Run:
    git.commit(sha, git.head, pr_head)
    return flow.run(sha, renders, branch=f"trunk-merge/{sha}", purpose=RunPurpose.OBSERVE)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestLedgerFlow:
    def test_approval_carries_over_a_push_lands_after_the_queue_reproduces_it(self, repo, git, flow, finalize) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        first = flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="feat-1", pr_number=1)
        assert gating.count_gating(first) == 1

        finalize(first)

        assert _approvals(repo) == [(1, "b1", "b0", "b0", BaselineApprovalState.OPEN, "")]
        flow.commit_to_github.assert_not_called()
        flow.rerun.assert_not_called()

        # The default branch still renders the old picture, and a default-branch run records nothing.
        flow.run(SEED, {"Button": "b0", "Card": "c0"}, branch=DEFAULT_BRANCH, purpose=RunPurpose.OBSERVE)
        assert _approvals(repo) == [(1, "b1", "b0", "b0", BaselineApprovalState.OPEN, "")]

        git.open_pull_request(1, git.commit("p1b", "p1a"))
        second = flow.run("p1b", {"Button": "b1", "Card": "c0"}, branch="feat-1", pr_number=1)
        assert gating.count_gating(second) == 0
        assert len(_approvals(repo)) == 1

        queue = _queue_run(flow, git, "q1", "p1b", {"Button": "b1", "Card": "c0"})
        assert _drift(queue) == (0, 0, 0)

        git.merge(1, "m1")
        ledger_advance.advance(repo)

        assert _approvals(repo) == [(1, "b1", "b0", "b0", BaselineApprovalState.PROMOTED, "reproduced")]
        assert _ledger(repo) == {"Button": "b1", "Card": "c0"}
        default = flow.run("m1", {"Button": "b1", "Card": "c0"}, branch=DEFAULT_BRANCH, purpose=RunPurpose.OBSERVE)
        assert _drift(default) == (0, 0, 0)

    def test_queue_run_that_renders_the_old_baseline_voids_the_approval(self, repo, git, flow, finalize) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="feat-1", pr_number=1))

        queue = _queue_run(flow, git, "q1", "p1a", {"Button": "b0", "Card": "c0"})
        assert _drift(queue) == (0, 0, 0)

        git.merge(1, "m1")
        ledger_advance.advance(repo)

        assert _approvals(repo) == [(1, "b1", "b0", "b0", BaselineApprovalState.VOIDED, "not_reproduced")]
        assert _ledger(repo) == {"Button": "b0", "Card": "c0"}

    def test_approval_over_a_baseline_another_merge_moved_no_longer_applies(self, repo, git, flow, finalize) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        git.open_pull_request(2, git.commit("p2a", SEED))
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="feat-1", pr_number=1))
        finalize(flow.run("p2a", {"Button": "b2", "Card": "c0"}, branch="feat-2", pr_number=2))
        git.merge(1, "m1")
        ledger_advance.advance(repo)
        assert _ledger(repo) == {"Button": "b1", "Card": "c0"}

        git.open_pull_request(2, git.commit("p2b", "m1", "p2a"))
        rebased = flow.run("p2b", {"Button": "b2", "Card": "c0"}, branch="feat-2", pr_number=2)

        button = rebased.snapshots.get(identifier="Button")
        assert (button.result, button.baseline_hash) == ("changed", "b1")
        assert gating.count_gating(rebased) == 1
        record = record_for_run(rebased)
        assert record is not None and record.candidate_approval_ids == ()
        assert _approvals(repo)[1][4] == BaselineApprovalState.OPEN

    def test_stack_lands_parent_first_and_ends_at_the_child_picture(self, repo, git, flow, finalize) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="parent", pr_number=1))
        git.open_pull_request(2, git.commit("p2a", "p1a"))
        child = flow.run("p2a", {"Button": "b2", "Card": "c0"}, branch="child", pr_number=2)
        assert child.snapshots.get(identifier="Button").baseline_hash == "b1"
        finalize(child)

        queue = _queue_run(flow, git, "q1", "p2a", {"Button": "b2", "Card": "c0"})
        assert _drift(queue) == (0, 0, 0)

        git.merge(1, "m1")
        ledger_advance.advance(repo)
        git.merge(2, "m2")
        ledger_advance.advance(repo)

        # The tip rendered the child's picture, so the parent's picture never becomes a baseline.
        assert _approvals(repo) == [
            (1, "b1", "b0", "b0", BaselineApprovalState.VOIDED, "not_reproduced"),
            (2, "b2", "b0", "b1", BaselineApprovalState.PROMOTED, "reproduced"),
        ]
        assert _ledger(repo) == {"Button": "b2", "Card": "c0"}

    @pytest.mark.parametrize(
        "child_approved_after_parent",
        [
            pytest.param(False, id="child_approved_before_parent_approval"),
            pytest.param(True, id="child_approved_after_parent_approval"),
        ],
    )
    def test_stack_child_run_before_parent_approval_passes_the_queue_and_lands_its_picture(
        self, repo, git, flow, finalize, child_approved_after_parent
    ) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        git.open_pull_request(2, git.commit("p2a", "p1a"))
        child = flow.run("p2a", {"Button": "b2", "Card": "c0"}, branch="child", pr_number=2)
        if not child_approved_after_parent:
            finalize(child)
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="parent", pr_number=1))
        if child_approved_after_parent:
            finalize(child)
        assert _approvals(repo) == [
            (1, "b1", "b0", "b0", BaselineApprovalState.OPEN, ""),
            (2, "b2", "b0", "b0", BaselineApprovalState.OPEN, ""),
        ]

        queue = _queue_run(flow, git, "q1", "p2a", {"Button": "b2", "Card": "c0"})
        assert _drift(queue) == (0, 0, 0)
        record = record_for_run(queue)
        assert record is not None and record.conflicts == {}

        git.merge(1, "m1")
        ledger_advance.advance(repo)
        git.merge(2, "m2")
        ledger_advance.advance(repo)

        assert _approvals(repo) == [
            (1, "b1", "b0", "b0", BaselineApprovalState.VOIDED, "not_reproduced"),
            (2, "b2", "b0", "b0", BaselineApprovalState.PROMOTED, "reproduced"),
        ]
        assert _ledger(repo) == {"Button": "b2", "Card": "c0"}

    def test_a_merge_of_the_same_story_turns_the_other_approval_red_until_a_revert(
        self, repo, git, flow, finalize, django_capture_on_commit_callbacks
    ) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        git.open_pull_request(2, git.commit("p2a", SEED))
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="feat-1", pr_number=1))
        finalize(flow.run("p2a", {"Button": "b2", "Card": "c0"}, branch="feat-2", pr_number=2))
        assert _last_status(flow, "p2a") == ("success", "Visual changes approved")

        git.merge(1, "m1")
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            ledger_advance.advance(repo)

        assert _last_status(flow, "p2a") == (
            "failure",
            "Baseline changed after approval: 1 snapshot. Update the branch and review again",
        )

        git.open_pull_request(3, git.commit("p3a", "m1"))
        finalize(flow.run("p3a", {"Button": "b0", "Card": "c0"}, branch="revert-1", pr_number=3))
        git.merge(3, "m3")
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            ledger_advance.advance(repo)

        assert _ledger(repo)["Button"] == "b0"
        assert _last_status(flow, "p2a") == ("success", "Visual changes approved")

    def test_a_stack_child_stays_green_when_its_parent_lands(
        self, repo, git, flow, finalize, django_capture_on_commit_callbacks
    ) -> None:
        git.open_pull_request(1, git.commit("p1a", SEED))
        finalize(flow.run("p1a", {"Button": "b1", "Card": "c0"}, branch="parent", pr_number=1))
        git.open_pull_request(2, git.commit("p2a", "p1a"))
        finalize(flow.run("p2a", {"Button": "b2", "Card": "c0"}, branch="child", pr_number=2))
        flow.statuses.reset_mock()

        git.merge(1, "m1")
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            ledger_advance.advance(repo)

        assert _ledger(repo)["Button"] == "b1"
        assert _last_status(flow, "p2a") == ("success", "Visual changes approved")

    @pytest.mark.parametrize(
        ("between_hash", "top_ledger_base_hash"),
        [
            pytest.param("b9", "b0", id="an_unrelated_pull_request_lands_another_picture"),
            pytest.param("b0", "g1", id="a_revert_of_the_bottom_layer_lands"),
        ],
    )
    def test_a_landing_between_the_queue_run_and_the_stack_landing_conflicts_the_stack_top(
        self, repo, git, flow, between_hash, top_ledger_base_hash
    ) -> None:
        git.open_pull_request(1, git.commit("g1a", SEED))
        approve(repo, 1, "Button", "g1", commit_sha="g1a")
        _queue_run(flow, git, "q1", "g1a", {"Button": "g1", "Card": "c0"})
        git.merge(1, "m1", squash=True)
        ledger_advance.advance(repo)

        git.open_pull_request(2, git.commit("p2a", "g1a"))
        git.open_pull_request(3, git.commit("c3a", "p2a"))
        approve(repo, 2, "Button", "b1", effective_base_hash="g1", commit_sha="p2a")
        top = approve(
            repo, 3, "Button", "b2", ledger_base_hash=top_ledger_base_hash, effective_base_hash="b1", commit_sha="c3a"
        )
        batch = _queue_run(flow, git, "q2", "c3a", {"Button": "b2", "Card": "c0"})
        assert _drift(batch) == (0, 0, 0)

        git.open_pull_request(4, git.commit("u4a", "m1"))
        approve(repo, 4, "Button", between_hash, ledger_base_hash="g1", commit_sha="u4a")
        _queue_run(flow, git, "q3", "u4a", {"Button": between_hash, "Card": "c0"})
        git.merge(4, "m2", squash=True)
        ledger_advance.advance(repo)
        git.merge(2, "m3", squash=True)
        git.merge(3, "m4", squash=True)
        ledger_advance.advance(repo)

        top.refresh_from_db()
        assert top.state == BaselineApprovalState.CONFLICTED
        assert _ledger(repo)["Button"] == between_hash

    def test_a_quarantined_queue_run_does_not_land_an_approval_over_a_moved_baseline(self, repo, git, flow) -> None:
        git.open_pull_request(1, git.commit("x1a", SEED))
        stale = approve(repo, 1, "Button", "b1", commit_sha="x1a")
        git.open_pull_request(2, git.commit("y2a", SEED))
        approve(repo, 2, "Button", "b2", commit_sha="y2a")
        _queue_run(flow, git, "q1", "y2a", {"Button": "b2", "Card": "c0"})
        git.merge(2, "m1", squash=True)
        ledger_advance.advance(repo)

        QuarantinedIdentifier.objects.create(
            repo=repo, team_id=repo.team_id, identifier="Button", run_type=RunType.STORYBOOK, reason="flaky"
        )
        queue = _queue_run(flow, git, "q2", "x1a", {"Button": "b1", "Card": "c0"})
        assert _drift(queue) == (0, 0, 0)
        git.merge(1, "m2", squash=True)
        ledger_advance.advance(repo)

        stale.refresh_from_db()
        assert stale.state == BaselineApprovalState.CONFLICTED
        assert _ledger(repo)["Button"] == "b2"

    def test_a_stack_top_the_queue_run_left_out_of_its_overlay_does_not_land_over_a_moved_baseline(
        self, repo, git, flow
    ) -> None:
        git.open_pull_request(1, git.commit("g1a", SEED))
        approve(repo, 1, "Button", "g1", commit_sha="g1a")
        _queue_run(flow, git, "q1", "g1a", {"Button": "g1", "Card": "c0"})
        git.merge(1, "m1", squash=True)
        ledger_advance.advance(repo)

        git.open_pull_request(2, git.commit("p2a", "g1a"))
        git.open_pull_request(3, git.commit("c3a", "p2a"))
        git.open_pull_request(4, git.commit("x4a", "m1"))
        approve(repo, 2, "Button", "b1", effective_base_hash="g1", commit_sha="p2a")
        top = approve(repo, 3, "Button", "b2", effective_base_hash="b1", commit_sha="c3a")
        approve(repo, 4, "Button", "b9", ledger_base_hash="g1", commit_sha="x4a")
        # The render passes against the ledger only through a toleration, because the top layer and the
        # unrelated pull request conflict and leave the story out of the overlay.
        for baseline_hash in ("g1", "b2"):
            ToleratedHash.objects.create(
                repo=repo, team_id=repo.team_id, identifier="Button", baseline_hash=baseline_hash, alternate_hash="t1"
            )
        git.commit("q2", git.head, "c3a", "x4a")
        batch = flow.run("q2", {"Button": "t1", "Card": "c0"}, branch="trunk-merge/q2", purpose=RunPurpose.OBSERVE)
        record = record_for_run(batch)
        assert record is not None and record.conflicts == {"Button": (3, 4)}
        assert _drift(batch) == (0, 0, 0)

        git.merge(2, "m2", squash=True)
        git.merge(3, "m3", squash=True)
        ledger_advance.advance(repo)

        top.refresh_from_db()
        assert top.state == BaselineApprovalState.CONFLICTED
        assert _ledger(repo)["Button"] == "g1"

    def test_a_landing_after_a_seed_conflicts_the_stack_top_the_queue_run_applied(self, repo, git, flow) -> None:
        git.open_pull_request(1, git.commit("g1a", SEED))
        approve(repo, 1, "Button", "g1", commit_sha="g1a")
        _queue_run(flow, git, "q1", "g1a", {"Button": "g1", "Card": "c0"})
        git.merge(1, "m1", squash=True)
        ledger_advance.advance(repo)

        git.open_pull_request(2, git.commit("p2a", "g1a"))
        git.open_pull_request(3, git.commit("c3a", "p2a"))
        approve(repo, 2, "Button", "b1", effective_base_hash="g1", commit_sha="p2a")
        top = approve(repo, 3, "Button", "b2", effective_base_hash="b1", commit_sha="c3a")
        batch = _queue_run(flow, git, "q2", "c3a", {"Button": "b2", "Card": "c0"})
        assert _drift(batch) == (0, 0, 0)

        # The seed starts the positions again, so the next landing reuses the batch's merge-base position.
        ledger.seed_from_ledger(repo, "m1")
        git.open_pull_request(4, git.commit("u4a", "m1"))
        approve(repo, 4, "Button", "b9", ledger_base_hash="g1", commit_sha="u4a")
        _queue_run(flow, git, "q3", "u4a", {"Button": "b9", "Card": "c0"})
        git.merge(4, "m2", squash=True)
        ledger_advance.advance(repo)
        git.merge(2, "m3", squash=True)
        git.merge(3, "m4", squash=True)
        ledger_advance.advance(repo)

        top.refresh_from_db()
        assert top.state == BaselineApprovalState.CONFLICTED
        assert _ledger(repo)["Button"] == "b9"

    def test_a_stack_top_turns_red_when_the_middle_layer_approval_it_counts_through_is_superseded(
        self, repo, git, flow, finalize
    ) -> None:
        git.open_pull_request(1, git.commit("g1a", SEED))
        finalize(flow.run("g1a", {"Button": "g1", "Card": "c0"}, branch="bottom", pr_number=1))
        _queue_run(flow, git, "q1", "g1a", {"Button": "g1", "Card": "c0"})
        git.merge(1, "m1", squash=True)
        ledger_advance.advance(repo)

        git.open_pull_request(2, git.commit("p2a", "g1a"))
        finalize(flow.run("p2a", {"Button": "b1", "Card": "c0"}, branch="middle", pr_number=2))
        git.open_pull_request(3, git.commit("c3a", "p2a"))
        finalize(flow.run("c3a", {"Button": "b2", "Card": "c0"}, branch="top", pr_number=3))
        assert _last_status(flow, "c3a") == ("success", "Visual changes approved")

        git.open_pull_request(2, git.commit("p2b", "p2a"))
        finalize(flow.run("p2b", {"Button": "b9", "Card": "c0"}, branch="middle", pr_number=2))

        assert _last_status(flow, "c3a")[0] != "success"

    def test_a_merge_that_resolves_late_under_the_queue_run_conflicts_the_stack_top(self, repo, git, flow) -> None:
        git.open_pull_request(1, git.commit("g1a", SEED))
        approve(repo, 1, "Button", "g1", commit_sha="g1a")
        _queue_run(flow, git, "q1", "g1a", {"Button": "g1", "Card": "c0"})
        git.merge(1, "m1", squash=True)
        ledger_advance.advance(repo)

        git.open_pull_request(4, git.commit("u4a", "m1"))
        approve(repo, 4, "Button", "b9", ledger_base_hash="g1", commit_sha="u4a")
        _queue_run(flow, git, "q2", "u4a", {"Button": "b9", "Card": "c0"})
        # GitHub lists the merge commit before it shows the pull request as merged, so the commit stays unresolved.
        git.merge(4, "m2", squash=True, shown_as_merged=False)
        ledger_advance.advance(repo)
        assert _ledger(repo)["Button"] == "g1"

        git.open_pull_request(2, git.commit("p2a", "g1a"))
        git.open_pull_request(3, git.commit("c3a", "p2a"))
        approve(repo, 2, "Button", "b1", effective_base_hash="g1", commit_sha="p2a")
        top = approve(repo, 3, "Button", "b2", effective_base_hash="b1", commit_sha="c3a")
        batch = _queue_run(flow, git, "q3", "c3a", {"Button": "b2", "Card": "c0"})
        assert _drift(batch) == (0, 0, 0)

        git.show_as_merged(4, "m2")
        ledger_advance.advance(repo)
        assert _ledger(repo)["Button"] == "b9"
        git.merge(2, "m3", squash=True)
        git.merge(3, "m4", squash=True)
        ledger_advance.advance(repo)

        top.refresh_from_db()
        assert top.state == BaselineApprovalState.CONFLICTED
        assert _ledger(repo)["Button"] == "b9"
