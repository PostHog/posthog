import pytest

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import BaselineApprovalState, BaselineMode, RunPurpose, RunType
from products.visual_review.backend.logic import approvals, gating, ledger, ledger_advance
from products.visual_review.backend.logic.baseline_record import record_for_run
from products.visual_review.backend.models import BaselineApproval, Repo, Run
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import (
    DEFAULT_BRANCH,
    SEED,
    FakeGit,
    LedgerFlow,
    seeded_repo,
)

RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
GREEN = (0, 255, 0, 255)
GREY = (128, 128, 128, 255)


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
