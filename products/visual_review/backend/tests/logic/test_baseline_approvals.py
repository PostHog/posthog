from datetime import UTC, datetime, timedelta

import pytest

from django.db import connections, transaction
from django.test.utils import CaptureQueriesContext

from products.visual_review.backend.classifier import ToleratedKey
from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import (
    BaselineApprovalState,
    BaselineEntrySource,
    BaselineEvidence,
    BaselineMode,
    ReviewState,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import baseline_approvals, baseline_resolution, ledger, repos
from products.visual_review.backend.logic.baseline_record import METADATA_KEY, BaselineRecord, OverlayEntry
from products.visual_review.backend.models import (
    BaselineApproval,
    QuarantinedIdentifier,
    Repo,
    Run,
    RunSnapshot,
    ToleratedHash,
)
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import (
    SEED,
    FakeGit,
    approve,
    make_record,
    move_ledger,
    seeded_repo,
)

APPROVED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def repo(team) -> Repo:
    return seeded_repo(team.id, BaselineMode.SHADOW)


@pytest.fixture
def git(mocker) -> FakeGit:
    return FakeGit(mocker, SEED)


def _run(
    repo: Repo,
    commit_sha: str,
    snapshots: dict[str, tuple[str, str, str]],
    *,
    record: BaselineRecord,
    purpose: RunPurpose = RunPurpose.OBSERVE,
    pr_number: int | None = None,
) -> Run:
    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=RunType.STORYBOOK,
        commit_sha=commit_sha,
        branch=f"trunk-merge/{commit_sha}" if pr_number is None else f"pr-{pr_number}",
        pr_number=pr_number,
        purpose=purpose,
        status=RunStatus.COMPLETED,
        metadata={METADATA_KEY: record.to_json()},
    )
    for identifier, (result, current_hash, baseline_hash) in snapshots.items():
        RunSnapshot.objects.create(
            run=run,
            team_id=repo.team_id,
            identifier=identifier,
            result=result,
            current_hash=current_hash,
            baseline_hash=baseline_hash,
            approved_hash=current_hash if result != SnapshotResult.REMOVED else "",
            review_state=ReviewState.APPROVED if purpose == RunPurpose.REVIEW else "",
        )
    return run


def _tolerate(repo: Repo, identifier: str, baseline_hash: str, alternate_hash: str) -> None:
    ToleratedHash.objects.create(
        repo=repo,
        team_id=repo.team_id,
        identifier=identifier,
        baseline_hash=baseline_hash,
        alternate_hash=alternate_hash,
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestEvidence:
    @pytest.mark.parametrize(
        ("snapshots", "tolerated", "expected"),
        [
            # A shadow run classifies against the YAML, so only the hash test sees the approved picture.
            pytest.param(
                {"Button": ("changed", "t1", "b0")}, [("b1", "t1")], BaselineEvidence.REPRODUCED, id="tolerated_render"
            ),
            pytest.param({"Button": ("unchanged", "b0", "b0")}, [], BaselineEvidence.NOT_REPRODUCED, id="old_baseline"),
        ],
    )
    def test_outcome(self, repo, git, snapshots, tolerated, expected) -> None:
        approval = approve(repo, 8, "Button", "b1")
        for baseline_hash, alternate_hash in tolerated:
            _tolerate(repo, "Button", baseline_hash, alternate_hash)
        run = _run(repo, "q1", snapshots, record=make_record(candidate_approval_ids=(approval.id,)))

        baseline_approvals.record_evidence(run)

        approval.refresh_from_db()
        assert (approval.evidence, approval.evidence_run_id, approval.evidence_commit_sha) == (expected, run.id, "q1")

    def test_evidence_from_an_older_run_never_replaces_a_newer_one(self, repo, git) -> None:
        approval = approve(repo, 8, "Button", "b1")
        record = make_record(candidate_approval_ids=(approval.id,))
        older = _run(repo, "q1", {"Button": ("unchanged", "b0", "b0")}, record=record)
        newer = _run(repo, "q2", {"Button": ("unchanged", "b1", "b1")}, record=record)
        Run.objects.filter(id=older.id).update(created_at=newer.created_at - timedelta(minutes=5))
        older.refresh_from_db()

        baseline_approvals.record_evidence(newer)
        baseline_approvals.record_evidence(older)

        approval.refresh_from_db()
        assert (approval.evidence, approval.evidence_run_id) == (BaselineEvidence.REPRODUCED, newer.id)

    def test_carried_commit_follows_the_pull_request_run_that_reproduced_the_approval(self, repo, git) -> None:
        reproduced = approve(repo, 8, "Button", "b1")
        not_reproduced = approve(repo, 8, "Card", "c1", ledger_base_hash="c0")

        baseline_approvals.record_carried_commits(
            _run(
                repo,
                "p8-rebased",
                {"Button": ("unchanged", "b1", "b1"), "Card": ("changed", "c2", "c1")},
                record=make_record(),
                purpose=RunPurpose.REVIEW,
                pr_number=8,
            )
        )

        reproduced.refresh_from_db()
        not_reproduced.refresh_from_db()
        assert (reproduced.carried_commit_sha, not_reproduced.carried_commit_sha) == ("p8-rebased", "")

    @pytest.mark.parametrize(
        ("mode", "quarantined", "expected_state"),
        [
            (BaselineMode.LEDGER, False, BaselineApprovalState.SUPERSEDED),
            (BaselineMode.LEDGER, True, BaselineApprovalState.OPEN),
            (BaselineMode.SHADOW, False, BaselineApprovalState.OPEN),
        ],
    )
    def test_a_pull_request_run_back_on_the_baseline_supersedes_its_open_approval(
        self, repo, git, mode, quarantined, expected_state
    ) -> None:
        repo.baseline_mode = mode
        repo.save()
        approval = approve(repo, 8, "Button", "b1")
        if quarantined:
            QuarantinedIdentifier.objects.create(
                repo=repo, team_id=repo.team_id, identifier="Button", run_type=RunType.STORYBOOK, reason="flaky"
            )

        baseline_approvals.record_carried_commits(
            _run(
                repo,
                "p8-reverted",
                {"Button": ("unchanged", "b0", "b0")},
                record=make_record(),
                purpose=RunPurpose.REVIEW,
                pr_number=8,
            )
        )

        approval.refresh_from_db()
        assert approval.state == expected_state
        if expected_state == BaselineApprovalState.SUPERSEDED:
            assert approval.detail == baseline_approvals.DETAIL_BACK_TO_BASELINE

    def test_a_run_superseded_while_it_finished_leaves_the_newer_runs_approvals_alone(self, repo, git) -> None:
        repo.baseline_mode = BaselineMode.LEDGER
        repo.save()
        older = _run(
            repo,
            "p8a",
            {"Button": ("unchanged", "b0", "b0"), "Card": ("unchanged", "c1", "c1")},
            record=make_record(),
            purpose=RunPurpose.REVIEW,
            pr_number=8,
        )
        newer = Run.objects.create(
            repo=repo, team_id=repo.team_id, run_type=RunType.STORYBOOK, commit_sha="p8b", branch="pr-8b", pr_number=8
        )
        Run.objects.filter(id=older.id).update(superseded_by=newer)
        button = approve(repo, 8, "Button", "b1")
        card = approve(repo, 8, "Card", "c1", ledger_base_hash="c0")

        baseline_approvals.record_carried_commits(older)

        button.refresh_from_db()
        card.refresh_from_db()
        assert (button.state, card.state, card.carried_commit_sha) == (
            BaselineApprovalState.OPEN,
            BaselineApprovalState.OPEN,
            "",
        )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRecordApprovals:
    def test_a_new_approval_supersedes_the_open_one_and_going_back_to_the_baseline_writes_none(self, repo) -> None:
        earlier_button = approve(repo, 8, "Button", "b1")
        earlier_card = approve(repo, 8, "Card", "c1", ledger_base_hash="c0")
        run = _run(
            repo,
            "p8b",
            {"Button": ("changed", "b2", "b1"), "Card": ("changed", "c0", "c1")},
            record=make_record(
                overlay={
                    "Button": OverlayEntry(
                        content_hash="b1", approval_id=earlier_button.id, pr_number=8, ledger_hash="b0"
                    ),
                    "Card": OverlayEntry(content_hash="c1", approval_id=earlier_card.id, pr_number=8, ledger_hash="c0"),
                }
            ),
            purpose=RunPurpose.REVIEW,
            pr_number=8,
        )

        with transaction.atomic(using=WRITER_DB):
            written = baseline_approvals.record_approvals(run, user_id=1)

        assert written == 1
        assert set(
            BaselineApproval.objects.filter(repo=repo).values_list("identifier", "content_hash", "state", "detail")
        ) == {
            ("Button", "b1", BaselineApprovalState.SUPERSEDED, baseline_approvals.DETAIL_SUPERSEDED),
            ("Card", "c1", BaselineApprovalState.SUPERSEDED, baseline_approvals.DETAIL_BACK_TO_BASELINE),
            ("Button", "b2", BaselineApprovalState.OPEN, ""),
        }
        new = BaselineApproval.objects.get(repo=repo, state=BaselineApprovalState.OPEN)
        assert (new.ledger_base_hash, new.effective_base_hash, new.commit_sha) == ("b0", "b1", "p8b")
        assert new.base_approval_id == earlier_button.id
        assert {earlier_button.id, earlier_card.id}.isdisjoint({new.id})

    @pytest.mark.parametrize(
        ("mode", "stamped_baseline", "overlay_ledger_hash", "differences", "snapshot", "expected_base"),
        [
            (BaselineMode.LEDGER, "b0", None, None, ("Button", "changed", "b2"), "b0"),
            (BaselineMode.LEDGER, "o1", "b0", None, ("Button", "changed", "b2"), "b0"),
            (BaselineMode.SHADOW, "y0", None, {"Button": "b0"}, ("Button", "changed", "b2"), "b0"),
            (BaselineMode.SHADOW, "o1", "b0", {"Button": "o1"}, ("Button", "changed", "b2"), "b0"),
            (BaselineMode.SHADOW, "y0", None, {}, ("Card", "removed", ""), "c0"),
        ],
    )
    def test_the_ledger_base_is_the_one_the_run_resolved_against_not_a_later_landing(
        self, repo, mode, stamped_baseline, overlay_ledger_hash, differences, snapshot, expected_base
    ) -> None:
        identifier, result, current_hash = snapshot
        overlay = {}
        if overlay_ledger_hash is not None:
            other = approve(repo, 9, "Button", "o1")
            overlay = {
                "Button": OverlayEntry(
                    content_hash="o1", approval_id=other.id, pr_number=9, ledger_hash=overlay_ledger_hash
                )
            }
        run = _run(
            repo,
            "p8b",
            {identifier: (result, current_hash, stamped_baseline)},
            record=make_record(mode=mode, overlay=overlay, differences=differences),
            purpose=RunPurpose.REVIEW,
            pr_number=8,
        )
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            ledger.append_entry(
                repo,
                run_type=RunType.STORYBOOK,
                identifier="Button",
                content_hash="late",
                previous_hash="b0",
                position=0,
                commit_sha=SEED,
                source=BaselineEntrySource.MERGE,
            )

        with transaction.atomic(using=WRITER_DB):
            baseline_approvals.record_approvals(run, user_id=1)

        new = BaselineApproval.objects.get(repo=repo, pr_number=8, state=BaselineApprovalState.OPEN)
        assert (new.ledger_base_hash, new.effective_base_hash) == (expected_base, stamped_baseline)

    def test_a_run_without_a_usable_record_writes_nothing(self, repo) -> None:
        run = _run(
            repo,
            "p8b",
            {"Button": ("changed", "b2", "b0")},
            record=BaselineRecord.unavailable(BaselineMode.SHADOW, "GitHub is down"),
            purpose=RunPurpose.REVIEW,
            pr_number=8,
        )

        with transaction.atomic(using=WRITER_DB):
            assert baseline_approvals.record_approvals(run, user_id=1) == 0

        assert not BaselineApproval.objects.filter(repo=repo).exists()


def _made_on_the_run(repo: Repo, approval: BaselineApproval) -> Run:
    run = _run(
        repo, "p8a", {"Button": ("changed", "b1", "b0")}, record=make_record(), purpose=RunPurpose.REVIEW, pr_number=8
    )
    Run.objects.filter(id=run.id).update(approved=True)
    BaselineApproval.objects.filter(id=approval.id).update(source_run=run)
    run.refresh_from_db()
    return run


def _made_on_the_run_and_quarantined(repo: Repo, approval: BaselineApproval) -> Run:
    run = _made_on_the_run(repo, approval)
    RunSnapshot.objects.filter(run=run).update(is_quarantined=True)
    return run


def _applied_as_overlay(repo: Repo, approval: BaselineApproval) -> Run:
    overlay = {"Button": OverlayEntry(content_hash="b1", approval_id=approval.id, pr_number=7, ledger_hash="b0")}
    record = make_record(overlay=overlay, candidate_approval_ids=(approval.id,))
    return _run(repo, "p8a", {"Button": ("changed", "b1", "b0")}, record=record, purpose=RunPurpose.REVIEW, pr_number=8)


def _candidate_the_overlay_dropped(repo: Repo, approval: BaselineApproval) -> Run:
    record = make_record(candidate_approval_ids=(approval.id,))
    return _run(repo, "p8a", {"Button": ("changed", "b1", "b0")}, record=record, purpose=RunPurpose.REVIEW, pr_number=8)


def _overlay_of(approval: BaselineApproval) -> BaselineRecord:
    overlay = {
        approval.identifier: OverlayEntry(
            content_hash=approval.content_hash,
            approval_id=approval.id,
            pr_number=approval.pr_number,
            ledger_hash=approval.ledger_base_hash,
        )
    }
    return make_record(overlay=overlay, candidate_approval_ids=(approval.id,))


def _passes_unchanged_on(repo: Repo, approval: BaselineApproval, commit_sha: str = "p8a") -> Run:
    return _run(
        repo,
        commit_sha,
        {"Button": ("unchanged", approval.content_hash, approval.content_hash)},
        record=_overlay_of(approval),
        purpose=RunPurpose.REVIEW,
        pr_number=8,
    )


def _approved_over(
    repo: Repo, lower: BaselineApproval, commit_sha: str, content_hash: str, **fields
) -> tuple[Run, BaselineApproval]:
    approving_run = _run(
        repo,
        commit_sha,
        {"Button": ("changed", content_hash, lower.content_hash)},
        record=_overlay_of(lower),
        purpose=RunPurpose.REVIEW,
        pr_number=8,
    )
    Run.objects.filter(id=approving_run.id).update(approved=True)
    approving_run.refresh_from_db()
    BaselineApproval.objects.filter(pr_number=8, state=BaselineApprovalState.OPEN).update(
        state=BaselineApprovalState.SUPERSEDED
    )
    approval = approve(
        repo, 8, "Button", content_hash, effective_base_hash=lower.content_hash, source_run=approving_run, **fields
    )
    return approving_run, approval


def _run_again_after(repo: Repo, old_run: Run, approval: BaselineApproval) -> Run:
    # A branch allows one unsuperseded run, so the old run points at itself until the new run exists.
    Run.objects.filter(id=old_run.id).update(superseded_by=old_run)
    rerun = _passes_unchanged_on(repo, approval, "p8z")
    Run.objects.filter(id=old_run.id).update(superseded_by=rerun)
    return rerun


def _child_approved_over_the_parent(repo: Repo, parent: BaselineApproval) -> Run:
    child_run, _child = _approved_over(repo, parent, "p8a", "b2")
    return child_run


def _child_runs_again_on_its_own_approval(repo: Repo, parent: BaselineApproval) -> Run:
    child_run, child = _approved_over(repo, parent, "p8a", "b2")
    return _run_again_after(repo, child_run, child)


def _child_runs_again_after_retention_deleted_the_approving_run(repo: Repo, parent: BaselineApproval) -> Run:
    child_run, child = _approved_over(repo, parent, "p8a", "b2", base_approval=parent)
    rerun = _run_again_after(repo, child_run, child)
    child_run.delete()
    return rerun


def _child_approves_again_over_its_own_approval(repo: Repo, parent: BaselineApproval) -> Run:
    first_run, first = _approved_over(repo, parent, "p8a", "b2")
    Run.objects.filter(id=first_run.id).update(superseded_by=first_run)
    second_run, _second = _approved_over(repo, first, "p8b", "b3")
    Run.objects.filter(id=first_run.id).update(superseded_by=second_run)
    return second_run


class TestIsStale:
    @pytest.mark.parametrize(
        ("content_hash", "ledger_base_hash", "effective_base_hash", "current_hash", "stale"),
        [
            pytest.param("b1", "b0", "b0", "b0", False, id="nothing_changed"),
            pytest.param("b2", "b0", "b1", "b1", False, id="parent_landed_on_the_effective_base"),
            pytest.param("b1", "b0", "b0", "b1", False, id="approved_picture_landed"),
            pytest.param("b1", "b0", "b0", "b9", True, id="another_picture_landed"),
            pytest.param("n1", "", "", "", False, id="new_story_still_absent"),
            pytest.param("n1", "", "", "n9", True, id="new_story_added_by_someone_else"),
            pytest.param("", "c0", "c0", "c9", True, id="approved_removal_of_a_story_that_changed"),
            pytest.param("", "c0", "c0", "", False, id="approved_removal_landed"),
        ],
    )
    def test_is_stale(self, content_hash, ledger_base_hash, effective_base_hash, current_hash, stale) -> None:
        approval = BaselineApproval(
            content_hash=content_hash, ledger_base_hash=ledger_base_hash, effective_base_hash=effective_base_hash
        )

        assert baseline_approvals.is_stale(approval, current_hash) is stale


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestStaleApprovals:
    @pytest.mark.parametrize(
        ("pr_number", "fields", "make_run", "stale"),
        [
            pytest.param(8, {}, _made_on_the_run, True, id="made_on_the_run"),
            pytest.param(8, {}, _made_on_the_run_and_quarantined, False, id="quarantined"),
            pytest.param(8, {"state": "superseded"}, _made_on_the_run, False, id="superseded"),
            pytest.param(8, {"state": "promoted"}, _made_on_the_run, False, id="promoted"),
            pytest.param(7, {}, _applied_as_overlay, True, id="applied_as_overlay"),
            pytest.param(7, {}, _candidate_the_overlay_dropped, False, id="candidate_the_overlay_dropped"),
        ],
    )
    def test_the_approvals_a_run_rests_on(self, repo, pr_number, fields, make_run, stale) -> None:
        made = approve(repo, pr_number, "Button", "b1", **fields)
        run = make_run(repo, made)
        move_ledger(repo, "Button", "b9")

        assert [approval.id for approval in baseline_approvals.stale_approvals(run)] == ([made.id] if stale else [])

    @pytest.mark.parametrize(
        ("middle_state", "stale"),
        [
            pytest.param(BaselineApprovalState.OPEN, False, id="middle_layer_open"),
            pytest.param(BaselineApprovalState.VOIDED, True, id="middle_layer_voided"),
            pytest.param(BaselineApprovalState.SUPERSEDED, True, id="middle_layer_superseded"),
        ],
    )
    def test_a_stack_layer_stays_fresh_only_while_the_layer_below_counts(self, repo, middle_state, stale) -> None:
        middle = approve(repo, 7, "Button", "b1", effective_base_hash="g1", state=middle_state)
        top = approve(repo, 8, "Button", "b2", effective_base_hash="b1")
        overlay = {"Button": OverlayEntry(content_hash="b1", approval_id=middle.id, pr_number=7, ledger_hash="b0")}
        record = make_record(overlay=overlay, candidate_approval_ids=(middle.id,))
        run = _run(
            repo, "p8a", {"Button": ("changed", "b2", "b1")}, record=record, purpose=RunPurpose.REVIEW, pr_number=8
        )
        Run.objects.filter(id=run.id).update(approved=True)
        BaselineApproval.objects.filter(id=top.id).update(source_run=run)
        run.refresh_from_db()
        # The bottom layer of the stack landed alone.
        move_ledger(repo, "Button", "g1")

        assert [approval.id for approval in baseline_approvals.stale_approvals(run)] == ([top.id] if stale else [])

    @pytest.mark.parametrize(
        ("parent_pr_number", "make_run"),
        [
            pytest.param(7, _passes_unchanged_on, id="stack_child_overlay"),
            pytest.param(8, _passes_unchanged_on, id="later_run_of_the_same_pull_request"),
            pytest.param(7, _child_approved_over_the_parent, id="child_approved_over_the_parent"),
            pytest.param(7, _child_runs_again_on_its_own_approval, id="child_runs_again_on_its_own_approval"),
            pytest.param(
                7,
                _child_runs_again_after_retention_deleted_the_approving_run,
                id="child_runs_again_after_retention_deleted_the_approving_run",
            ),
            pytest.param(7, _child_approves_again_over_its_own_approval, id="child_approves_again_over_its_own"),
        ],
    )
    @pytest.mark.parametrize(
        ("parent_state", "stale"),
        [
            pytest.param(BaselineApprovalState.OPEN, False, id="open"),
            pytest.param(BaselineApprovalState.PROMOTED, False, id="promoted"),
            pytest.param(BaselineApprovalState.SUPERSEDED, True, id="superseded"),
            pytest.param(BaselineApprovalState.VOIDED, True, id="voided"),
            pytest.param(BaselineApprovalState.CONFLICTED, True, id="conflicted"),
            pytest.param(BaselineApprovalState.ABANDONED, True, id="abandoned"),
        ],
    )
    def test_an_applied_approval_that_closed_without_a_ledger_entry(
        self, repo, parent_pr_number, make_run, parent_state, stale
    ) -> None:
        parent = approve(repo, parent_pr_number, "Button", "b1")
        run = make_run(repo, parent)
        # The ledger still holds b0, so the moved-base rule alone finds nothing stale.
        BaselineApproval.objects.filter(id=parent.id).update(state=parent_state)

        assert [approval.id for approval in baseline_approvals.stale_approvals(run)] == ([parent.id] if stale else [])

    def test_an_approval_over_a_lower_layer_that_nothing_names_any_more_is_stale(self, repo) -> None:
        parent = approve(repo, 7, "Button", "b1")
        # Written before approvals named their base approval, so only the approving run's overlay names the parent.
        child_run, child = _approved_over(repo, parent, "p8a", "b2")
        rerun = _run_again_after(repo, child_run, child)
        child_run.delete()

        assert [approval.id for approval in baseline_approvals.stale_approvals(rerun)] == [child.id]

    def test_the_walk_stops_at_a_promoted_layer(self, repo) -> None:
        bottom = approve(repo, 6, "Button", "b1", state=BaselineApprovalState.ABANDONED)
        middle = approve(
            repo,
            7,
            "Button",
            "b2",
            effective_base_hash="b1",
            base_approval=bottom,
            state=BaselineApprovalState.PROMOTED,
        )
        top_run, _top = _approved_over(repo, middle, "p8a", "b3", base_approval=middle)

        assert baseline_approvals.stale_approvals(top_run) == []

    @pytest.mark.parametrize(
        "cover",
        [
            "back_to_baseline",
            "same_picture_approved_again",
            "ledger_holds_the_picture",
            "ledger_holds_the_child_base",
            "reverted_to_the_ledger",
            "same_picture_approved_again_over_an_open_layer",
        ],
    )
    def test_a_closed_approval_whose_picture_is_still_covered_is_not_stale(self, repo, cover) -> None:
        parent = approve(repo, 7, "Button", "b1")
        if cover == "back_to_baseline":
            run = _run(
                repo,
                "p8a",
                {"Button": ("changed", "b0", "b1")},
                record=_overlay_of(parent),
                purpose=RunPurpose.REVIEW,
                pr_number=8,
            )
            Run.objects.filter(id=run.id).update(approved=True)
            run.refresh_from_db()
        elif cover == "ledger_holds_the_child_base":
            run = _child_runs_again_on_its_own_approval(repo, parent)
        elif cover == "reverted_to_the_ledger":
            # The pull request pushed a revert: the run renders the ledger's picture with nothing to review.
            run = _run(
                repo,
                "p7b",
                {"Button": ("unchanged", "b0", "b0")},
                record=_overlay_of(parent),
                purpose=RunPurpose.REVIEW,
                pr_number=7,
            )
        else:
            run = _passes_unchanged_on(repo, parent)
        BaselineApproval.objects.filter(id=parent.id).update(state=BaselineApprovalState.SUPERSEDED)
        if cover == "same_picture_approved_again":
            approve(repo, 7, "Button", "b1")
        if cover == "same_picture_approved_again_over_an_open_layer":
            # The parent re-approved b1 over an open layer's b2, and that layer counts once b3 lands.
            approve(repo, 6, "Button", "b2", effective_base_hash="b3")
            approve(repo, 7, "Button", "b1", effective_base_hash="b2")
            move_ledger(repo, "Button", "b3")
        if cover in ("ledger_holds_the_picture", "ledger_holds_the_child_base"):
            move_ledger(repo, "Button", "b1")

        assert baseline_approvals.stale_approvals(run) == []

    def test_nothing_is_stale_without_a_record(self, repo) -> None:
        run = _made_on_the_run(repo, approve(repo, 8, "Button", "b1"))
        move_ledger(repo, "Button", "b9")
        Run.objects.filter(id=run.id).update(metadata={})
        run.refresh_from_db()

        assert baseline_approvals.stale_approvals(run) == []

    def test_nothing_is_stale_without_a_ledger(self, team) -> None:
        unseeded = repos.create_repo(team_id=team.id, repo_external_id=66100, repo_full_name="org/no-ledger")
        # Against an empty ledger the approval's base b0 is gone, so only the missing cursor keeps it fresh.
        run = _made_on_the_run(unseeded, approve(unseeded, 8, "Button", "b1"))

        assert baseline_approvals.stale_approvals(run) == []

    def test_a_run_without_approvals_or_overlay_reads_nothing(self, repo) -> None:
        run = _run(repo, "p8a", {}, record=make_record(), purpose=RunPurpose.REVIEW, pr_number=8)

        with CaptureQueriesContext(connections[WRITER_DB]) as queries:
            assert baseline_approvals.stale_approvals(run) == []

        assert len(queries) == 0

    def test_a_run_with_its_own_approval_over_an_open_parent_reads_no_run(self, repo) -> None:
        parent = approve(repo, 7, "Button", "b1")
        child_run, _child = _approved_over(repo, parent, "p8a", "b2")

        with CaptureQueriesContext(connections[WRITER_DB]) as queries:
            assert baseline_approvals.stale_approvals(child_run) == []

        assert [query["sql"] for query in queries if 'FROM "visual_review_run"' in query["sql"]] == []
        assert len(queries) == 6

    def test_a_long_chain_of_one_pull_request_costs_no_more_queries_than_a_short_one(self, repo) -> None:
        def queries_for_chain(pr_number: int, links: int) -> int:
            parent = approve(repo, pr_number, "Button", f"{pr_number}-p", ledger_base_hash="b0")
            lower = parent
            for link in range(links):
                lower = approve(
                    repo,
                    pr_number + 1,
                    "Button",
                    f"{pr_number}-{link}",
                    effective_base_hash=lower.content_hash,
                    base_approval=lower,
                    state=BaselineApprovalState.SUPERSEDED,
                )
            top = approve(
                repo,
                pr_number + 1,
                "Button",
                f"{pr_number}-top",
                effective_base_hash=lower.content_hash,
                base_approval=lower,
            )
            walk = baseline_approvals.LowerLayerWalk({"Button": "b0"})
            with CaptureQueriesContext(connections[WRITER_DB]) as queries:
                assert walk.closed_bases([top]) == {}
            return len(queries)

        assert queries_for_chain(10, 1) == queries_for_chain(20, 8)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestWithoutClosedLowerLayers:
    @pytest.mark.parametrize(
        ("parent_state", "ledger_hash", "child_counts"),
        [
            pytest.param(BaselineApprovalState.OPEN, "b0", True, id="parent_open"),
            pytest.param(BaselineApprovalState.PROMOTED, "b0", True, id="parent_promoted"),
            pytest.param(BaselineApprovalState.ABANDONED, "b0", False, id="parent_abandoned"),
            pytest.param(BaselineApprovalState.VOIDED, "b0", False, id="parent_voided"),
            pytest.param(BaselineApprovalState.VOIDED, "b1", True, id="parent_voided_but_its_picture_landed"),
        ],
    )
    def test_a_child_approved_over_a_closed_parent_stops_counting(
        self, repo, parent_state, ledger_hash, child_counts
    ) -> None:
        parent = approve(repo, 7, "Button", "b1", state=parent_state)
        child = approve(repo, 8, "Button", "b2", effective_base_hash="b1", base_approval=parent)

        kept = baseline_approvals.without_closed_lower_layers([parent, child], {"Button": ledger_hash})

        assert [approval.id for approval in kept] == [parent.id, *([child.id] if child_counts else [])]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestCompareShadow:
    @pytest.mark.parametrize(
        ("name", "snapshot", "differences", "truncated", "expected_pairs", "gate_differs"),
        [
            ("equal_baselines", ("changed", "b1", "b0"), {}, {}, {}, False),
            ("ledger_only_green", ("changed", "b1", "b0"), {"Button": "b1"}, {}, {"changed/unchanged": 1}, True),
            ("ledger_only_red", ("unchanged", "b0", "b0"), {"Button": ""}, {}, {"unchanged/new": 1}, True),
            ("undetermined", ("changed", "b2", "b0"), {"Button": "b1"}, {}, {"changed/undetermined": 1}, False),
            (
                "differences_truncated",
                ("changed", "b1", "b0"),
                {"Button": "b1"},
                {"differences_truncated": True},
                {"changed/unchanged": 1},
                None,
            ),
            ("ledger_removed_truncated", ("changed", "b1", "b0"), {}, {"ledger_removed_truncated": True}, {}, None),
        ],
    )
    def test_comparison(self, repo, name, snapshot, differences, truncated, expected_pairs, gate_differs) -> None:
        run = _run(
            repo,
            "p8",
            {"Button": snapshot},
            record=make_record(mode=BaselineMode.SHADOW, differences=differences, ledger_removed=(), **truncated),
            pr_number=8,
            purpose=RunPurpose.REVIEW,
        )

        comparison = baseline_resolution.compare_shadow(run)

        assert comparison is not None
        assert (comparison.pairs, comparison.gate_differs) == (expected_pairs, gate_differs)
        run.refresh_from_db()
        stored = BaselineRecord.from_json(run.metadata[METADATA_KEY])
        assert stored is not None and stored.comparison == comparison

    def test_removals_only_one_side_reports_change_the_gate(self, repo) -> None:
        run = _run(
            repo,
            "p8",
            {"Button": ("unchanged", "b0", "b0"), "Card": ("removed", "", "c0")},
            record=make_record(mode=BaselineMode.SHADOW, differences={}, ledger_removed=()),
            pr_number=8,
            purpose=RunPurpose.REVIEW,
        )

        comparison = baseline_resolution.compare_shadow(run)

        assert comparison is not None
        assert (comparison.yaml_only_removed, comparison.ledger_only_removed) == (("Card",), ())
        assert comparison.gate_differs is True


def _approval(identifier: str, content_hash: str, pr_number: int, *, base: str = "b0", **fields) -> BaselineApproval:
    return BaselineApproval(
        run_type=RunType.STORYBOOK,
        identifier=identifier,
        content_hash=content_hash,
        pr_number=pr_number,
        ledger_base_hash=base,
        effective_base_hash=fields.pop("effective_base_hash", base),
        approved_at=fields.pop("approved_at", APPROVED_AT),
        **fields,
    )


class TestReduceOverlay:
    @pytest.mark.parametrize(
        ("candidates", "parents", "entries", "conflicts", "applied"),
        [
            pytest.param(
                {"own": _approval("Button", "b1", 8)}, None, {"Button": "own"}, {}, ["own"], id="one_approval"
            ),
            pytest.param({"moved": _approval("Button", "b1", 8, base="older")}, None, {}, {}, [], id="base_moved"),
            pytest.param(
                {
                    "parent": _approval("Button", "b1", 7, approved_at=APPROVED_AT - timedelta(minutes=20)),
                    "child": _approval("Button", "b2", 8, effective_base_hash="b1"),
                },
                None,
                {"Button": "child"},
                {},
                ["parent", "child"],
                id="stack_child_wins_over_its_parent",
            ),
            pytest.param(
                {"first": _approval("Card", "c1", 9, base="c0"), "second": _approval("Card", "c2", 7, base="c0")},
                None,
                {},
                {"Card": (7, 9)},
                ["first", "second"],
                id="two_pull_requests_conflict",
            ),
            pytest.param(
                {
                    "older": _approval("Card", "c1", 7, base="c0", approved_at=APPROVED_AT - timedelta(minutes=5)),
                    "newer": _approval("Card", "c1", 9, base="c0"),
                },
                None,
                {"Card": "newer"},
                {},
                ["older", "newer"],
                id="the_same_picture_from_two_pull_requests_takes_the_newest",
            ),
            pytest.param(
                {
                    "parent": _approval("Button", "b1", 7),
                    "revert": _approval("Button", "b0", 8, effective_base_hash="b1"),
                },
                None,
                {},
                {},
                ["parent", "revert"],
                id="a_cycle_applies_nothing",
            ),
            pytest.param(
                {
                    "parent": _approval(
                        "Button", "b1", 7, commit_sha="p7", approved_at=APPROVED_AT - timedelta(minutes=20)
                    ),
                    "child": _approval("Button", "b2", 8, commit_sha="c8", effective_base_hash="b1"),
                },
                {"c8": ("p7",), "p7": ("s0",)},
                {"Button": "child"},
                {},
                ["parent", "child"],
                id="stack_child_run_after_parent_approval_wins_with_a_commit_graph",
            ),
            pytest.param(
                {
                    "child": _approval(
                        "Button", "b2", 8, commit_sha="c8", approved_at=APPROVED_AT - timedelta(minutes=20)
                    ),
                    "parent": _approval("Button", "b1", 7, commit_sha="p7"),
                },
                {"c8": ("p7",), "p7": ("s0",)},
                {"Button": "child"},
                {},
                ["child", "parent"],
                id="stack_child_run_and_approval_before_parent_approval_wins",
            ),
            pytest.param(
                {
                    "parent": _approval(
                        "Button", "b1", 7, commit_sha="p7", approved_at=APPROVED_AT - timedelta(minutes=20)
                    ),
                    "child": _approval("Button", "b2", 8, commit_sha="c8"),
                },
                {"c8": ("p7",), "p7": ("s0",)},
                {"Button": "child"},
                {},
                ["parent", "child"],
                id="stack_child_run_before_parent_approval_approved_after_it_wins",
            ),
            pytest.param(
                {
                    "child": _approval(
                        "Button", "b2", 8, commit_sha="c8", approved_at=APPROVED_AT - timedelta(minutes=20)
                    ),
                    "parent": _approval("Button", "b1", 7, commit_sha="p7"),
                },
                {},
                {},
                {"Button": (7, 8)},
                ["child", "parent"],
                id="stack_child_run_before_parent_approval_conflicts_when_the_commits_are_unknown",
            ),
            pytest.param(
                {
                    "first": _approval("Card", "c1", 9, base="c0", commit_sha="a9"),
                    "second": _approval("Card", "c2", 7, base="c0", commit_sha="a7"),
                },
                {"a9": ("s0",), "a7": ("s0",)},
                {},
                {"Card": (7, 9)},
                ["first", "second"],
                id="two_unrelated_pull_requests_conflict_with_a_commit_graph",
            ),
            pytest.param(
                {
                    "middle": _approval("Button", "b1", 7, base="older", effective_base_hash="b0"),
                    "top": _approval("Button", "b2", 8, base="older", effective_base_hash="b1"),
                },
                None,
                {"Button": "top"},
                {},
                ["middle", "top"],
                id="stack_top_counts_through_the_open_middle_layer_after_the_bottom_landed",
            ),
            pytest.param(
                {"top": _approval("Button", "b2", 8, base="older", effective_base_hash="b1")},
                None,
                {},
                {},
                [],
                id="stack_top_does_not_count_once_the_middle_layer_approval_is_gone",
            ),
            pytest.param(
                {
                    "middle": _approval("Button", "b1", 7, base="older", effective_base_hash="older"),
                    "top": _approval("Button", "b2", 8, base="older", effective_base_hash="b1"),
                },
                None,
                {},
                {},
                [],
                id="stack_top_does_not_count_through_a_middle_layer_whose_base_moved",
            ),
        ],
    )
    def test_reduce_overlay(self, candidates, parents, entries, conflicts, applied) -> None:
        ledger_hashes = {"Button": "b0", "Card": "c0"}
        commit_graph = None if parents is None else baseline_approvals.CommitGraph(parents=parents)

        overlay = baseline_approvals.reduce_overlay(list(candidates.values()), ledger_hashes, commit_graph)

        assert overlay.entries == {
            identifier: OverlayEntry(
                content_hash=candidates[name].content_hash,
                approval_id=candidates[name].id,
                pr_number=candidates[name].pr_number,
                ledger_hash=ledger_hashes[identifier],
            )
            for identifier, name in entries.items()
        }
        assert overlay.conflicts == conflicts
        assert overlay.candidate_approval_ids == tuple(candidates[name].id for name in applied)


class TestRenderedApprovedHash:
    @pytest.mark.parametrize(
        ("content_hash", "snapshot", "is_partial", "reproduced"),
        [
            pytest.param("b1", ("unchanged", "b1", "b1"), False, True, id="same_hash"),
            pytest.param(
                "b1", ("unchanged", "b1-noise", "b1"), False, True, id="unchanged_against_the_approved_baseline"
            ),
            pytest.param("b1", ("changed", "t1", "b0"), False, True, id="tolerated_render"),
            pytest.param("b1", ("unchanged", "b0", "b0"), False, False, id="old_baseline"),
            pytest.param("b1", None, False, False, id="not_rendered"),
            pytest.param("b1", ("removed", "", "b0"), False, False, id="rendered_as_removed"),
            pytest.param("", None, False, True, id="removal_not_rendered"),
            pytest.param("", ("removed", "", "b0"), False, True, id="removal_reported_as_removed"),
            pytest.param("", None, True, False, id="removal_missing_from_a_partial_run"),
            pytest.param("", ("unchanged", "b0", "b0"), False, False, id="removal_still_rendered"),
        ],
    )
    def test_rendered_approved_hash(self, content_hash, snapshot, is_partial, reproduced) -> None:
        approval = BaselineApproval(identifier="Button", content_hash=content_hash)
        rendered = None
        if snapshot is not None:
            result, current_hash, baseline_hash = snapshot
            rendered = RunSnapshot(
                identifier="Button", result=result, current_hash=current_hash, baseline_hash=baseline_hash
            )
        tolerated = {ToleratedKey(identifier="Button", baseline_hash="b1", current_hash="t1"): ToleratedHash()}

        assert baseline_approvals.rendered_approved_hash(approval, rendered, is_partial, tolerated) is reproduced
