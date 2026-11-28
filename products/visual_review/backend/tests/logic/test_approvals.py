"""Unit tests for logic/approvals.py — Approving snapshots and finalizing a run."""

from contextlib import ExitStack
from datetime import timedelta

import pytest
from unittest.mock import MagicMock

from django.db import connections, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from posthog.models import Organization, User
from posthog.models.user_integration import UserIntegration
from posthog.paging import PageRequest

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import (
    ActorType,
    BaselineMode,
    DecisionAction,
    DecisionChannel,
    ReviewState,
    RunGate,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import (
    approvals,
    artifact_store,
    baselines,
    ci_status,
    errors,
    gating,
    github_api,
    repos,
    retention,
    run_queries,
    runs,
    toleration,
)
from products.visual_review.backend.logic.github_api import PullRequestState
from products.visual_review.backend.models import BaselineApproval, QuarantinedIdentifier, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, FakeGit, LedgerFlow, approve, button_flow


def _fake_github_job_api(method, repo, path, **kwargs):
    if method == "GET":
        return MagicMock(status_code=200, json=lambda: {"head_sha": "abc", "run_id": 777})
    return MagicMock(status_code=201)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveRun:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_approve_run(self, repo, user, mocker):
        current_artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash="new_hash", storage_path="p/new"
        )
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert updated.approved is True
        assert updated.review_decision == "human_approved"
        assert updated.approved_at is not None
        assert updated.approved_by_id == user.id

        # Result should NOT be mutated - approval is recorded separately
        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.result == SnapshotResult.CHANGED  # Result preserved
        assert snapshot.approved_hash == "new_hash"  # Approval recorded
        assert snapshot.reviewed_at is not None
        assert snapshot.reviewed_by_id == user.id

    def _completed_change_run(self, repo, mocker, identifiers=("A", "B")):
        for identifier in identifiers:
            artifact_store.get_or_create_artifact(
                repo_id=repo.id, content_hash=f"h{identifier.lower()}", storage_path=f"p/{identifier.lower()}"
            )
        baseline_hashes = {identifier: f"old{identifier.lower()}" for identifier in identifiers}
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier=identifier, content_hash=f"h{identifier.lower()}")
                    for identifier in identifiers
                ],
                baseline_hashes=baseline_hashes,
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline_hashes, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run

    def test_finalize_requires_full_resolution(self, repo, user, mocker):
        # Finalize is all-or-nothing: it refuses while any changed/new snapshot is unreviewed.
        run = self._completed_change_run(repo, mocker)

        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "A", "new_hash": "ha"}]
        )
        with pytest.raises(errors.RunNotFullyResolvedError) as refused:
            approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)
        assert refused.value.needs_review == ["B"]

        # Resolving the rest lets it finalize.
        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "B", "new_hash": "hb"}]
        )
        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)
        assert updated.approved is True

    def test_finalize_leaves_tolerated_snapshot_alone(self, repo, user, mocker):
        # A tolerated snapshot resolves the run without being approved or committed.
        run = self._completed_change_run(repo, mocker)
        snap_b = run.snapshots.get(identifier="B")
        toleration.mark_snapshot_as_tolerated(run.id, snap_b.id, user.id, repo.team_id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert updated.approved is True
        snapshots = {s.identifier: s for s in updated.snapshots.all()}
        assert snapshots["A"].review_state == ReviewState.APPROVED
        assert snapshots["B"].review_state == ReviewState.TOLERATED  # approve_all did not clobber it

    def test_finalize_is_idempotent_on_approved_run(self, repo, user, mocker):
        # Re-finalizing an already-finalized run is a no-op — no second commit/status/comment.
        run = self._completed_change_run(repo, mocker)
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
        approved_at = run_queries.get_run_with_snapshots(run.id).approved_at

        again = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert again.approved is True
        assert again.approved_at == approved_at  # unchanged — the second call did no work

    def test_approve_all_query_count_does_not_grow_with_the_snapshots(self, repo, user, mocker):
        query_counts = []
        for identifiers in (("A", "B"), ("C", "D", "E", "F", "G", "H")):
            run = self._completed_change_run(repo, mocker, identifiers)
            contexts = [CaptureQueriesContext(connections[alias]) for alias in sorted(PRODUCT_DATABASES)]
            with ExitStack() as stack:
                for context in contexts:
                    stack.enter_context(context)
                approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
            query_counts.append(sum(len(context.captured_queries) for context in contexts))

        assert query_counts[0] == query_counts[1]

    @pytest.mark.parametrize(
        ("approve", "tolerate", "expected"),
        [
            ([], [], 2),
            (["A"], ["B"], 1),
            ([], ["A", "B"], 0),
        ],
    )
    def test_completing_again_reports_what_still_fails_the_gate(self, repo, user, mocker, approve, tolerate, expected):
        # A re-run of the completing CI job calls complete on a finished run and gates on this
        # count, so an untouched or approved-but-uncommitted change must still count.
        run = self._completed_change_run(repo, mocker)
        for identifier in tolerate:
            toleration.mark_snapshot_as_tolerated(
                run.id, run.snapshots.get(identifier=identifier).id, user.id, repo.team_id
            )
        approvals.approve_snapshots(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": i, "new_hash": f"h{i.lower()}"} for i in approve],
        )

        assert api.complete_run(run.id, team_id=repo.team_id).summary.unresolved == expected

    @pytest.mark.parametrize("add_images", [True, False])
    def test_finalize_always_comments_and_forwards_add_images(self, repo, user, mocker, add_images):
        # The PR comment is always dispatched on finalize; add_images_to_comment_on_pr only
        # controls whether the snapshot images are embedded — forwarded to the task.
        run = self._completed_change_run(repo, mocker)
        mocker.patch.object(ci_status, "_post_commit_status")
        mocker.patch.object(transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        delay = mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        approvals.finalize_run(
            run_id=run.id,
            user_id=user.id,
            approve_all=True,
            commit_to_github=True,
            add_images_to_comment_on_pr=add_images,
        )

        assert delay.called is True
        assert delay.call_args.args[2] is add_images

    @pytest.mark.parametrize(
        ("result", "approve_all", "expect_committed"),
        [
            ("new", False, True),
            ("changed", False, True),
            ("new", True, False),
            ("changed", True, False),
        ],
    )
    def test_finalize_commits_quarantined_only_when_approved_by_identifier(
        self, repo, user, mocker, result, approve_all, expect_committed
    ):
        # An explicit approval commits a quarantined snapshot, so its baseline can follow the story.
        # approve_all never touches quarantine, so a flapping hash cannot land in bulk.
        run = self._completed_quarantined_run(repo, mocker, result)
        if not approve_all:
            approvals.approve_snapshots(
                run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "Q", "new_hash": "hq"}]
            )
        commit = mocker.patch.object(baselines, "_commit_baseline_to_github")
        mocker.patch.object(ci_status, "_post_commit_status")
        github = mocker.patch.object(github_api, "_github_api_request", side_effect=_fake_github_job_api)
        mocker.patch.object(transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=approve_all)

        assert updated.approved is True
        if expect_committed:
            assert commit.call_args.args[2] == [{"identifier": "Q", "new_hash": "hq"}]
        else:
            assert commit.called is False
        reruns = [c.args[2] for c in github.call_args_list if c.args[0] == "POST"]
        assert reruns == ([] if expect_committed else ["actions/jobs/42/rerun"])

    def _completed_quarantined_run(self, repo, mocker, result):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="hq", storage_path="p/q")
        baseline = {} if result == "new" else {"Q": "oldq"}
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=7,
                snapshots=[SnapshotManifestItem(identifier="Q", content_hash="hq")],
                baseline_hashes=baseline,
                metadata={"github_check_run_id": "42", "github_run_id": "777"},
            ),
            team_id=repo.team_id,
        )
        QuarantinedIdentifier.objects.create(
            repo=repo, team_id=repo.team_id, identifier="Q", run_type=RunType.STORYBOOK, reason="test"
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=(baseline, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveSnapshots:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99998, repo_full_name="org/test-snap")

    def test_approve_single_snapshot_db_only(self, repo, user, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="new_hash", storage_path="p/new")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.approve_snapshots(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "Button", "new_hash": "new_hash"}],
        )

        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.review_state == "approved"
        assert snapshot.approved_hash == "new_hash"

        # Run-level state should NOT change
        assert updated.approved is False
        assert updated.review_decision == "pending"


def _changed_run(git: FakeGit, flow: LedgerFlow) -> Run:
    git.open_pull_request(1, git.commit("p1a", SEED))
    return flow.run("p1a", {"Button": "b1"}, branch="feat", pr_number=1)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestFinalizeByBaselineMode:
    @pytest.mark.parametrize(
        ("mode", "commits", "writes_approval"),
        [
            (BaselineMode.YAML, True, False),
            (BaselineMode.SHADOW, True, True),
            (BaselineMode.LEDGER, False, True),
        ],
    )
    def test_finalize_commits_records_and_never_reruns_by_mode(
        self, team, user, mocker, django_capture_on_commit_callbacks, mode, commits, writes_approval
    ):
        repo, git, flow = button_flow(team.id, mode, mocker, external_id=99997)
        run = _changed_run(git, flow)

        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert flow.commit_to_github.called is commits
        assert BaselineApproval.objects.filter(repo=repo, pr_number=1, content_hash="b1").exists() is writes_approval
        assert flow.rerun.called is False

    @pytest.mark.parametrize(
        ("created_in", "gate", "reruns"),
        [(BaselineMode.SHADOW, RunGate.CI_JOB, True), (BaselineMode.LEDGER, RunGate.COMMIT_STATUS, False)],
    )
    def test_finalize_reruns_the_completing_job_by_the_gate_the_run_was_created_with(
        self, team, user, mocker, django_capture_on_commit_callbacks, created_in, gate, reruns
    ):
        repo, git, flow = button_flow(team.id, created_in, mocker, external_id=99997)
        run = _changed_run(git, flow)
        repo.baseline_mode = BaselineMode.SHADOW
        repo.save()
        snapshot = run.snapshots.get(identifier="Button")

        # A tolerated change leaves nothing to commit, so only a re-run can turn the job green.
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id)
            approvals.finalize_run(run_id=run.id, user_id=user.id)

        run.refresh_from_db()
        assert run.gate == gate
        assert flow.commit_to_github.called is False
        assert flow.rerun.called is reruns

    def test_shadow_finalize_makes_no_github_request_of_its_own(self, team, user, mocker):
        _repo, git, flow = button_flow(team.id, BaselineMode.SHADOW, mocker, external_id=99997)
        run = _changed_run(git, flow)
        pull_request_state = mocker.patch.object(github_api, "pull_request_state")

        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert pull_request_state.called is False

    @pytest.mark.parametrize(
        ("pull_request", "run_fields", "error"),
        [
            (
                PullRequestState(state="closed", merged=True, merge_commit_sha="m1", base_ref="master", head_sha="p1a"),
                {},
                errors.PullRequestClosedError,
            ),
            (
                PullRequestState(state="open", merged=False, merge_commit_sha=None, base_ref="master", head_sha="p1b"),
                {},
                errors.PRSHAMismatchError,
            ),
            (None, {"metadata": {}}, errors.RunWithoutBaselineRecordError),
            (None, {"pr_number": None}, errors.RunWithoutPullRequestError),
        ],
    )
    def test_ledger_finalize_refuses_before_any_write(self, team, user, mocker, pull_request, run_fields, error):
        repo, git, flow = button_flow(team.id, BaselineMode.LEDGER, mocker, external_id=99997)
        run = _changed_run(git, flow)
        if pull_request is not None:
            git.pull_requests[1] = pull_request
        if run_fields:
            Run.objects.filter(id=run.id).update(**run_fields)

        with pytest.raises(error):
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        run.refresh_from_db()
        assert run.approved is False
        assert not run.snapshots.filter(review_state=ReviewState.APPROVED).exists()
        assert not BaselineApproval.objects.filter(repo=repo).exists()

    def test_finalize_refuses_when_the_mode_changed_before_it_took_its_locks(self, team, user, mocker):
        repo, git, flow = button_flow(team.id, BaselineMode.LEDGER, mocker, external_id=99997)
        run = _changed_run(git, flow)
        # The mode finalize read before its transaction, which picks the locks it takes.
        mocker.patch.object(
            approvals,
            "_read_finalize_context",
            return_value=approvals._FinalizeContext(
                repo_id=repo.id, mode=BaselineMode.YAML, run_type=run.run_type, pr_number=1
            ),
        )

        with pytest.raises(errors.BaselineModeChangedError):
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        run.refresh_from_db()
        assert run.approved is False
        assert not run.snapshots.filter(metadata__has_key="review_decisions").exists()

    @pytest.mark.parametrize("mode", [BaselineMode.YAML, BaselineMode.SHADOW])
    @pytest.mark.parametrize(
        ("request_fields", "code"),
        [
            pytest.param({"identifier": "Button", "new_hash": None}, "hash_required", id="removed_without_hash"),
            pytest.param(
                {"identifier": "Card", "new_hash": "b1", "old_hash": "b0"}, "hash_mismatch", id="another_baseline"
            ),
        ],
    )
    def test_an_accept_outside_ledger_mode_is_refused_by_name(self, team, user, mocker, mode, request_fields, code):
        _repo, git, flow = button_flow(team.id, mode, mocker, external_id=99997)
        git.open_pull_request(1, git.commit("p1a", SEED))
        run = flow.run("p1a", {"Card": "b1"}, branch="feat", pr_number=1)

        with pytest.raises(errors.DecisionRefusedError) as refused:
            approvals.decide(
                run.id,
                user.id,
                DecisionAction.ACCEPT,
                [approvals.DecisionRequest(**request_fields)],
                via=DecisionChannel.MCP,
                team_id=run.team_id,
            )

        assert [(r.identifier, r.code) for r in refused.value.refusals] == [(request_fields["identifier"], code)]
        assert not run.snapshots.filter(review_state=ReviewState.APPROVED).exists()

    def test_a_snapshot_list_outside_ledger_mode_shows_no_decision(self, team, user, mocker):
        _repo, git, flow = button_flow(team.id, BaselineMode.YAML, mocker, external_id=99997)
        run = _changed_run(git, flow)
        approvals.decide(
            run.id,
            user.id,
            DecisionAction.ACCEPT,
            [approvals.DecisionRequest(identifier="Button", new_hash="b1")],
            via=DecisionChannel.MCP,
            team_id=run.team_id,
        )

        listed = api.get_run_snapshots(run.id, team_id=team.id).snapshots[0]

        assert (listed.review_state, listed.decision) == ("approved", None)

    def test_yaml_finalize_refuses_a_closed_pull_request(self, team, user, mocker):
        repo = repos.create_repo(team_id=team.id, repo_external_id=99997, repo_full_name="org/test-modes")
        run = Run.objects.create(
            repo=repo,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="p1a",
            branch="feat",
            pr_number=1,
            status=RunStatus.COMPLETED,
        )
        RunSnapshot.objects.create(
            run=run,
            team_id=repo.team_id,
            identifier="Button",
            result=SnapshotResult.CHANGED,
            current_hash="b1",
            baseline_hash="b0",
            approved_hash="b1",
            review_state=ReviewState.APPROVED,
        )
        integration = MagicMock()
        integration.api_request.return_value = MagicMock(
            status_code=200, json=lambda: {"head": {"ref": "feat", "sha": "p1a"}, "state": "closed", "merged": True}
        )
        mocker.patch.object(github_api, "get_github_integration_for_repo", return_value=integration)

        with pytest.raises(errors.PullRequestClosedError):
            approvals.finalize_run(run_id=run.id, user_id=user.id)

        run.refresh_from_db()
        assert run.approved is False


GREEN = (0, 255, 0, 255)
ACCEPT = DecisionAction.ACCEPT
REJECT = DecisionAction.REJECT
CLEAR = DecisionAction.CLEAR
WEB = DecisionChannel.WEB
MCP = DecisionChannel.MCP


def _push(git: FakeGit, flow: LedgerFlow, sha: str, parent: str, renders: dict[str, str], **fields) -> Run:
    git.open_pull_request(1, git.commit(sha, parent))
    return flow.run(sha, renders, branch="feat", pr_number=1, **fields)


def _decide(run: Run, user, action: DecisionAction, via: DecisionChannel = WEB, **fields) -> approvals.DecisionOutcome:
    kwargs = {key: fields.pop(key) for key in ("expected_seq", "override_rejection") if key in fields}
    request = approvals.DecisionRequest(**{"identifier": "Button", **fields})
    return approvals.decide(run.id, user.id, action, [request], via=via, team_id=run.team_id, **kwargs)


def _history(run: Run, identifier: str = "Button") -> list[dict]:
    return run.snapshots.get(identifier=identifier).metadata.get("review_decisions", [])


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestReviewDecisions:
    @pytest.fixture
    def ledger(self, team, mocker):
        repo, git, flow = button_flow(team.id, BaselineMode.LEDGER, mocker, external_id=99996)
        flow.picture("b2", GREEN)
        return repo, git, flow

    @pytest.fixture
    def bob(self, team):
        bob = User.objects.create_and_join(team.organization, "bob@example.com", None, first_name="Robert")
        UserIntegration.objects.create(
            user=bob,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="4242",
            config={"github_user": {"login": "bob-gh", "id": 4242}},
            sensitive_config={"user_access_token": "ghu_fake"},
        )
        return bob

    @pytest.mark.parametrize(("picture", "finalizes"), [("b1", True), ("b2", False)])
    def test_an_accept_on_an_older_run_counts_while_the_pictures_match(
        self, ledger, team, user, bob, picture, finalizes
    ):
        repo, git, flow = ledger
        first = _changed_run(git, flow)
        _decide(first, bob, ACCEPT, new_hash="b1")
        head = _push(git, flow, "p1b", "p1a", {"Button": picture})

        listed = api.get_run_snapshots(head.id, team_id=team.id).snapshots[0]
        if not finalizes:
            assert listed.review_state == "pending"
            assert listed.decision is None
            assert listed.earlier_decision is not None and listed.earlier_decision.changed == "after"
            with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
                approvals.finalize_run(run_id=head.id, user_id=user.id)
            assert not_resolved.value.needs_review == ["Button"]
            return

        assert listed.review_state == "approved"
        assert listed.decision is not None and listed.decision.from_earlier_commit is True
        assert (listed.reviewed_at, listed.approved_hash) == (listed.decision.at, "b1")
        approvals.finalize_run(run_id=head.id, user_id=user.id)
        approval = BaselineApproval.objects.get(repo=repo, pr_number=1, identifier="Button")
        assert (approval.content_hash, approval.approved_by_id) == ("b1", bob.id)
        with pytest.raises(errors.DecisionRefusedError) as refused:
            _decide(first, bob, REJECT, new_hash="b1", reason="Too blue")
        assert refused.value.code == "run_finalized"

    def test_a_rejection_blocks_finalize_until_its_rejecter_undoes_it(
        self, ledger, team, user, bob, django_capture_on_commit_callbacks
    ):
        repo, git, flow = ledger
        run = _changed_run(git, flow)
        with django_capture_on_commit_callbacks(using=WRITER_DB, execute=True):
            _decide(run, bob, REJECT, new_hash="b1", reason="Too blue")

        # Named by GitHub login first, the way the PR comment names him.
        assert flow.statuses.call_args.kwargs["description"] == "Rejected by bob-gh: Button"
        snapshot = run.snapshots.get(identifier="Button")
        with pytest.raises(errors.SnapshotRejectedError):
            toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, team.id)
        QuarantinedIdentifier.objects.create(
            repo=repo, team_id=team.id, identifier="Button", run_type=RunType.STORYBOOK, reason="flaky"
        )
        with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)
        assert [(r.identifier, r.by_id, r.reason) for r in not_resolved.value.rejected] == [
            ("Button", bob.id, "Too blue")
        ]

        _decide(run, bob, CLEAR)
        assert approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True).approved is True

    @pytest.mark.parametrize(
        ("setup", "via", "action", "fields", "code"),
        [
            pytest.param("bob_rejects", MCP, ACCEPT, {"new_hash": "b1"}, "decided_by_person", id="agent_over_reject"),
            pytest.param(
                "bob_rejects",
                MCP,
                ACCEPT,
                {"new_hash": "b1", "override_rejection": True},
                "decided_by_person",
                id="agent_never_overrides",
            ),
            pytest.param("bob_accepts", MCP, CLEAR, {}, "decided_by_person", id="agent_undoes_a_person"),
            pytest.param("bob_rejects", WEB, ACCEPT, {"new_hash": "b1"}, "rejected_by_other", id="needs_override"),
            pytest.param(
                "bob_rejects", WEB, ACCEPT, {"new_hash": "b1", "override_rejection": True}, None, id="accept_anyway"
            ),
            pytest.param("bob_rejects", WEB, CLEAR, {}, "rejected_by_other", id="undo_needs_override"),
            pytest.param("bob_rejects", WEB, CLEAR, {"override_rejection": True}, None, id="undo_anyway"),
            pytest.param("user_rejects", WEB, CLEAR, {}, None, id="undo_own_reject"),
            pytest.param(
                "bob_rejects",
                WEB,
                REJECT,
                {"new_hash": "b1", "reason": "x", "expected_seq": 0},
                "decided_since",
                id="decided_since_the_read",
            ),
            pytest.param(
                "bob_rejects",
                WEB,
                ACCEPT,
                {"new_hash": "b1", "override_rejection": True, "expected_seq": 1},
                None,
                id="decided_on_the_seq_it_read",
            ),
            pytest.param("user_agent_rejects", MCP, ACCEPT, {"new_hash": "b1"}, "rejected_by_other", id="agent_own"),
            pytest.param("user_agent_rejects", MCP, CLEAR, {}, None, id="agent_undoes_its_own_reject"),
            pytest.param("bob_agent_rejects", MCP, CLEAR, {}, "rejected_by_other", id="agent_undoes_other_agent"),
            pytest.param(
                "finalized_then_pushed",
                WEB,
                REJECT,
                {"new_hash": "b1", "reason": "x"},
                "run_finalized",
                id="pair_of_a_finalized_run",
            ),
            pytest.param("", WEB, ACCEPT, {"new_hash": "b2"}, "hash_mismatch", id="other_after_picture"),
            pytest.param("", WEB, ACCEPT, {"new_hash": "b1", "old_hash": "b9"}, "hash_mismatch", id="other_before"),
            pytest.param("", WEB, ACCEPT, {}, "hash_required", id="no_hash"),
            pytest.param("", WEB, REJECT, {"new_hash": "b1", "reason": " "}, "reason_required", id="no_reason"),
            pytest.param("", WEB, ACCEPT, {"identifier": "Nope", "new_hash": "b1"}, "unknown_identifier", id="unknown"),
            pytest.param("merged", WEB, ACCEPT, {"new_hash": "b1"}, "pr_closed", id="merged_pull_request"),
        ],
    )
    def test_who_may_decide_what(self, ledger, user, bob, setup, via, action, fields, code):
        _repo, git, flow = ledger
        run = _changed_run(git, flow)
        if setup == "bob_rejects":
            _decide(run, bob, REJECT, new_hash="b1", reason="Too blue")
        elif setup == "bob_agent_rejects":
            _decide(run, bob, REJECT, via=MCP, new_hash="b1", reason="Too blue")
        elif setup == "user_rejects":
            _decide(run, user, REJECT, new_hash="b1", reason="Too blue")
        elif setup == "user_agent_rejects":
            _decide(run, user, REJECT, via=MCP, new_hash="b1", reason="Too blue")
        elif setup == "bob_accepts":
            _decide(run, bob, ACCEPT, new_hash="b1")
        elif setup == "finalized_then_pushed":
            _decide(run, bob, ACCEPT, new_hash="b1")
            approvals.finalize_run(run_id=run.id, user_id=bob.id)
            _push(git, flow, "p1b", "p1a", {"Button": "b1"})
        elif setup == "merged":
            git.show_as_merged(1, "m1")
        history = _history(run)

        if code is None:
            _decide(run, user, action, via=via, **fields)
            assert [entry["action"] for entry in _history(run)] == [*(e["action"] for e in history), action.value]
            return
        with pytest.raises(errors.DecisionRefusedError) as refused:
            _decide(run, user, action, via=via, **fields)
        assert refused.value.code == code
        assert _history(run) == history

    @pytest.mark.parametrize(
        ("history", "finalize_via", "refused"),
        [
            pytest.param([], WEB, None, id="undecided"),
            pytest.param([REJECT], WEB, "rejected", id="rejected"),
            pytest.param([ACCEPT, CLEAR], WEB, None, id="person_undid_person_finalizes"),
            pytest.param([ACCEPT, CLEAR], MCP, "needs_review", id="person_undid_agent_finalizes"),
        ],
    )
    def test_finalize_accepts_a_removal_unless_it_was_rejected_or_an_agent_would_replace_an_undo(
        self, ledger, user, bob, history, finalize_via, refused
    ):
        repo, git, flow = ledger
        run = _push(git, flow, "p1a", SEED, {"Card": "b1"})
        for action in history:
            if action == REJECT:
                _decide(run, bob, REJECT, new_hash=None, reason="Still in use")
            else:
                _decide(run, bob, action)
        if refused is not None:
            with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
                approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, via=finalize_via)
            assert {
                "rejected": [r.identifier for r in not_resolved.value.rejected],
                "needs_review": not_resolved.value.needs_review,
            }[refused] == ["Button"]
            return

        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, via=finalize_via)
        rows = BaselineApproval.objects.filter(repo=repo, pr_number=1).values_list("identifier", "content_hash")
        assert sorted(rows) == [("Button", ""), ("Card", "b1")]

    def test_a_toleration_after_an_accept_keeps_the_baseline_at_finalize(self, ledger, team, user, bob):
        repo, git, flow = ledger
        run = _changed_run(git, flow)
        _decide(run, bob, ACCEPT, new_hash="b1")

        toleration.mark_snapshot_as_tolerated(run.id, run.snapshots.get(identifier="Button").id, user.id, team.id)
        approvals.finalize_run(run_id=run.id, user_id=user.id)

        assert api.get_run_snapshots(run.id, team_id=team.id).snapshots[0].review_state == "tolerated"
        assert not BaselineApproval.objects.filter(repo=repo, pr_number=1, identifier="Button").exists()
        assert [entry["action"] for entry in _history(run)] == ["accept", "clear"]

    @pytest.mark.parametrize("history", [[ACCEPT], [ACCEPT, CLEAR]], ids=["person_accepted", "person_undid"])
    def test_an_agent_cannot_tolerate_over_a_persons_decision(self, ledger, team, user, bob, history):
        _repo, git, flow = ledger
        run = _changed_run(git, flow)
        for action in history:
            _decide(run, bob, action, new_hash="b1")
        snapshot = run.snapshots.get(identifier="Button")

        with pytest.raises(errors.DecidedByPersonError):
            toleration.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, team.id, actor=ActorType.AGENT)

        snapshot.refresh_from_db()
        assert snapshot.review_state != ReviewState.TOLERATED
        assert [entry["action"] for entry in _history(run)] == [action.value for action in history]

    def test_a_rejection_by_someone_outside_the_organization_still_blocks_and_names_nobody(self, ledger, team, user):
        _repo, git, flow = ledger
        run = _changed_run(git, flow)
        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "outsider@example.com", None
        )
        entry = {
            "action": "reject",
            "old_hash": "b0",
            "new_hash": "b1",
            "by": outsider.id,
            "reason": "Too blue",
            "at": "2026-01-01T00:00:00+00:00",
            "seq": 1,
        }
        RunSnapshot.objects.filter(run=run, identifier="Button").update(metadata={"review_decisions": [entry]})

        listed = api.get_run_snapshots(run.id, team_id=team.id).snapshots[0]
        with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
            approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert (listed.review_state, listed.decision is not None and listed.decision.by) == ("rejected", None)
        assert [(r.identifier, r.by_id) for r in not_resolved.value.rejected] == [("Button", None)]

    def test_a_partial_run_that_leaves_out_a_rejected_story_stays_blocked(self, ledger, user, bob):
        _repo, git, flow = ledger
        first = _changed_run(git, flow)
        _decide(first, bob, REJECT, new_hash="b1", reason="Too blue")
        head = _push(git, flow, "p1b", "p1a", {"Card": "b2"}, is_partial=True)

        assert gating.count_unresolved(head) == 2
        with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
            approvals.finalize_run(run_id=head.id, user_id=user.id, approve_all=True)
        assert [r.identifier for r in not_resolved.value.rejected] == ["Button"]

    def test_a_rejected_pair_that_a_toleration_makes_unchanged_can_be_undone_on_the_head(self, ledger, team, user, bob):
        _repo, git, flow = ledger
        first = _changed_run(git, flow)
        toleration.mark_snapshot_as_tolerated(first.id, first.snapshots.get(identifier="Button").id, user.id, team.id)
        _decide(first, bob, REJECT, new_hash="b1", reason="Too blue")
        head = _push(git, flow, "p1b", "p1a", {"Button": "b1"})
        assert head.snapshots.get(identifier="Button").result == SnapshotResult.UNCHANGED

        listed = api.get_run_snapshots(head.id, team_id=team.id, exclude_unchanged=True).snapshots
        assert [(s.identifier, s.review_state) for s in listed] == [("Button", "rejected")]
        with pytest.raises(errors.RunNotFullyResolvedError):
            approvals.finalize_run(run_id=head.id, user_id=user.id)

        _decide(head, bob, CLEAR)
        assert approvals.finalize_run(run_id=head.id, user_id=user.id).approved is True

    def test_retention_keeps_a_newer_rejection_on_an_older_run_while_the_head_holds_an_accept(
        self, ledger, team, user, bob
    ):
        repo, git, flow = ledger
        first = _changed_run(git, flow)
        head = _push(git, flow, "p1b", "p1a", {"Button": "b1"})
        _decide(head, user, ACCEPT, new_hash="b1")
        _decide(first, bob, REJECT, new_hash="b1", reason="Too blue")
        # An open approval of the pull request keeps the head through the quiet-branch pass.
        approve(repo, 1, "Card", "c1")

        retention.sweep_repo_runs(repo, now=timezone.now() + timedelta(days=40))

        assert Run.objects.filter(id=first.id).exists()
        with pytest.raises(errors.RunNotFullyResolvedError) as not_resolved:
            approvals.finalize_run(run_id=head.id, user_id=user.id)
        assert [r.identifier for r in not_resolved.value.rejected] == ["Button"]

    @pytest.mark.parametrize(
        "row",
        [
            pytest.param(lambda _outsider: {"metadata": {"review_decisions": "accept"}}, id="not_a_list"),
            pytest.param(lambda _outsider: {"metadata": {"review_decisions": ["accept"]}}, id="entry_not_an_object"),
            pytest.param(
                lambda _outsider: {"metadata": {"review_decisions": [{"action": "accept", "seq": 1}]}},
                id="entry_without_a_time",
            ),
            pytest.param(
                lambda _outsider: {
                    "metadata": {
                        "review_decisions": [{"action": "approve", "at": "2026-01-01T00:00:00+00:00", "seq": 1}]
                    }
                },
                id="unknown_action",
            ),
            pytest.param(
                lambda outsider: {
                    "metadata": {
                        "review_decisions": [
                            {
                                "action": "accept",
                                "old_hash": "b0",
                                "new_hash": "b1",
                                "by": outsider.id,
                                "at": "2026-01-01T00:00:00+00:00",
                                "seq": 1,
                            }
                        ]
                    }
                },
                id="entry_by_someone_outside_the_organization",
            ),
            pytest.param(
                lambda outsider: {"review_state": ReviewState.APPROVED, "reviewed_by_id": outsider.id},
                id="approval_by_someone_outside_the_organization",
            ),
            pytest.param(
                lambda outsider: {
                    "metadata": {
                        "review_decisions": [
                            {
                                "action": action,
                                "old_hash": "b0",
                                "new_hash": "b1",
                                "by": outsider.id,
                                "reason": "Too blue" if action == "reject" else "",
                                "at": f"2026-01-0{seq}T00:00:00+00:00",
                                "seq": seq,
                            }
                            for seq, action in enumerate(["reject", "clear"], start=1)
                        ]
                    }
                },
                id="rejection_retracted_by_someone_outside_the_organization",
            ),
        ],
    )
    def test_an_unreadable_or_untrusted_decision_entry_is_skipped(self, ledger, team, user, row):
        _repo, git, flow = ledger
        run = _changed_run(git, flow)
        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "outsider@example.com", None
        )
        RunSnapshot.objects.filter(run=run, identifier="Button").update(**row(outsider))

        listed = api.get_run_snapshots(run.id, team_id=team.id).snapshots[0]

        assert (listed.review_state, listed.decision) == ("pending", None)
        _decide(run, user, ACCEPT, new_hash="b1")
        assert approvals.finalize_run(run_id=run.id, user_id=user.id).approved is True

    def test_a_decider_resolves_only_within_the_organization(self, team, user):
        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "outsider@example.com", None
        )

        infos = api._fetch_decider_infos({user.id, outsider.id}, team.id)

        assert set(infos) == {user.id}

    @pytest.mark.parametrize(("card_accepted", "can_finalize"), [(True, True), (False, False)])
    def test_can_finalize_leaves_an_undecided_removal_to_finalize(
        self, ledger, team, user, card_accepted, can_finalize
    ):
        _repo, _git, flow = ledger
        flow.picture("c1", GREEN)
        run = _push(_git, flow, "p1a", SEED, {"Card": "c1"})
        if card_accepted:
            _decide(run, user, ACCEPT, identifier="Card", new_hash="c1")

        read = api.get_run(run.id, team_id=team.id)

        assert read.progress is not None and read.progress.needs_review == (1 if card_accepted else 2)
        assert read.can_finalize is can_finalize
        if can_finalize:
            assert approvals.finalize_run(run_id=run.id, user_id=user.id).approved is True

    def test_a_run_list_reads_no_decisions(self, ledger, team, user):
        repo, git, flow = ledger
        first = _changed_run(git, flow)
        _decide(first, user, ACCEPT, new_hash="b1")

        def list_queries() -> int:
            with CaptureQueriesContext(connections[WRITER_DB]) as queries:
                api.list_runs(team.id, repo_id=repo.id, page=PageRequest(limit=100))
            return len(queries)

        one_run = list_queries()
        _push(git, flow, "p1b", "p1a", {"Button": "b1"})
        _push(git, flow, "p1c", "p1b", {"Button": "b1"})

        assert list_queries() == one_run
