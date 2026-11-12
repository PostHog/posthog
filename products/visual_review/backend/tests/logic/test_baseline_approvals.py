from datetime import UTC, datetime, timedelta

import pytest

from django.db import transaction

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
from products.visual_review.backend.logic import baseline_approvals, baseline_resolution, ledger
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
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, FakeGit, approve, make_record, seeded_repo

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
        ("candidates", "entries", "conflicts", "applied"),
        [
            pytest.param({"own": _approval("Button", "b1", 8)}, {"Button": "own"}, {}, ["own"], id="one_approval"),
            pytest.param({"moved": _approval("Button", "b1", 8, base="older")}, {}, {}, [], id="base_moved"),
            pytest.param(
                {
                    "parent": _approval("Button", "b1", 7, approved_at=APPROVED_AT - timedelta(minutes=20)),
                    "child": _approval("Button", "b2", 8, effective_base_hash="b1"),
                },
                {"Button": "child"},
                {},
                ["parent", "child"],
                id="stack_child_wins_over_its_parent",
            ),
            pytest.param(
                {"first": _approval("Card", "c1", 9, base="c0"), "second": _approval("Card", "c2", 7, base="c0")},
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
                {},
                {},
                ["parent", "revert"],
                id="a_cycle_applies_nothing",
            ),
        ],
    )
    def test_reduce_overlay(self, candidates, entries, conflicts, applied) -> None:
        ledger_hashes = {"Button": "b0", "Card": "c0"}

        overlay = baseline_approvals.reduce_overlay(list(candidates.values()), ledger_hashes)

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
