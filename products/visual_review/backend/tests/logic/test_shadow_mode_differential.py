from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.db import connections

from products.visual_review.backend import diffing
from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import BaselineMode, RunPurpose, RunStatus, RunType
from products.visual_review.backend.logic import (
    approvals,
    artifact_store,
    baseline_approvals,
    baseline_resolution,
    baselines,
    ci_status,
    comments,
    ledger,
    quarantine,
    repos,
    run_queries,
    runs,
    toleration,
)
from products.visual_review.backend.models import QuarantinedIdentifier, Repo, Run, RunSnapshot
from products.visual_review.backend.tasks import tasks
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import DEFAULT_BRANCH, SEED, FakeGit, solid_png

YAML_BASELINE = {"Button": "b0", "Card": "c0"}
PICTURES = {"b0": (255, 0, 0, 255), "b1": (0, 0, 255, 255), "c0": (128, 128, 128, 255)}
CHANGED = {"Button": "b1", "Card": "c0"}

YAML = "yaml"
SHADOW = "shadow"
SHADOW_FAILING = "shadow_failing"
SHADOW_LEDGER_BUSY = "shadow_ledger_busy"

_TASKS = (
    ("process_run_diffs", "delay"),
    ("emit_run_processing_metrics", "delay"),
    ("post_approval_comment", "delay"),
    ("reconcile_quarantine_lifts", "delay"),
    ("notify_quarantine_owners", "apply_async"),
)


def _fail_in_sql(*args: Any, **kwargs: Any) -> None:
    with connections[WRITER_DB].cursor() as cursor:
        cursor.execute("SELECT 1/0")


class _Harness:
    def __init__(self, team_id: int, user_id: int, variant: str, external_id: int, mocks: dict[str, MagicMock]):
        self.team_id = team_id
        self.user_id = user_id
        self.variant = variant
        self.mocks = mocks
        self.repo = repos.create_repo(team_id=team_id, repo_external_id=external_id, repo_full_name=f"org/{variant}")
        Repo.objects.filter(id=self.repo.id).update(enable_pr_comments=True)
        for content_hash in PICTURES:
            artifact_store.get_or_create_artifact(self.repo.id, content_hash, f"visual_review/{content_hash}")
        if variant != YAML:
            ledger.seed(self.repo, SEED, {RunType.STORYBOOK: YAML_BASELINE})
            ledger.set_baseline_mode(self.repo, BaselineMode.SHADOW)
        self.repo.refresh_from_db()

    @contextmanager
    def ledger_faults(self) -> Iterator[None]:
        with ExitStack() as stack:
            if self.variant == SHADOW_FAILING:
                for module, name in (
                    (baseline_resolution, "resolve_ledger_baseline"),
                    (baseline_resolution, "compare_shadow"),
                    (baseline_approvals, "record_approvals"),
                    (baseline_approvals, "record_evidence"),
                    (baseline_approvals, "record_carried_commits"),
                ):
                    stack.enter_context(patch.object(module, name, side_effect=_fail_in_sql))
            if self.variant == SHADOW_LEDGER_BUSY:
                stack.enter_context(patch.object(ledger, "try_lock_ledger", return_value=False))
            yield

    def create(self, commit_sha: str, renders: dict[str, str], **fields: Any) -> Run:
        run, _uploads = runs.create_run(
            CreateRunInput(
                repo_id=self.repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha=commit_sha,
                branch=fields.get("branch", "feat"),
                pr_number=fields.get("pr_number", 1),
                purpose=fields.get("purpose", RunPurpose.REVIEW),
                is_partial=fields.get("is_partial", False),
                snapshots=[SnapshotManifestItem(identifier=i, content_hash=h) for i, h in renders.items()],
                metadata={"github_check_run_id": "42", "github_run_id": "777"},
            ),
            team_id=self.team_id,
        )
        return run

    def run(self, commit_sha: str, renders: dict[str, str], **fields: Any) -> Run:
        run = self.create(commit_sha, renders, **fields)
        if runs.complete_run(run.id).status == RunStatus.PROCESSING:
            diffing.process_diffs(run.id)
            runs.finish_processing(run.id)
        return run_queries.get_run(run.id)

    def snapshot(self, run: Run, identifier: str) -> RunSnapshot:
        return RunSnapshot.objects.get(run_id=run.id, identifier=identifier)

    def outcome(self, result: Any) -> dict[str, Any]:
        repo_runs = list(Run.objects.filter(repo_id=self.repo.id).order_by("commit_sha", "branch", "created_at"))
        names = {str(run.id): f"<run {index}>" for index, run in enumerate(repo_runs)} | {str(self.repo.id): "<repo>"}

        def plain(value: Any) -> Any:
            if isinstance(value, str):
                return names.get(value, value)
            if isinstance(value, (list, tuple)):
                return [plain(item) for item in value]
            if isinstance(value, dict):
                return {key: plain(item) for key, item in value.items()}
            return value

        return {
            "result": plain(result),
            "runs": [
                (
                    run.status,
                    run.purpose,
                    run.is_partial,
                    run.total_snapshots,
                    run.changed_count,
                    run.new_count,
                    run.removed_count,
                    run.tolerated_match_count,
                    run.approved,
                    run.review_decision,
                    run.error_message,
                    [
                        (s.identifier, s.result, s.baseline_hash, s.review_state, s.approved_hash, s.is_quarantined)
                        for s in RunSnapshot.objects.filter(run_id=run.id).order_by("identifier")
                    ],
                )
                for run in repo_runs
            ],
            "baseline_commits": [
                (call.args[0].commit_sha, sorted(update["identifier"] for update in call.args[2]))
                for call in self.mocks["commit"].call_args_list
            ],
            "job_reruns": [(call.args[0].commit_sha, call.args[1]) for call in self.mocks["rerun"].call_args_list],
            "review_prompts": [call.args[0].commit_sha for call in self.mocks["prompt"].call_args_list],
            "tasks": [
                (name, plain(list(call.args)), plain(call.kwargs))
                for name, _method in _TASKS
                for call in self.mocks[name].call_args_list
            ],
        }


def _result(scenario: Callable[["_Harness"], Any], harness: "_Harness") -> Any:
    try:
        value = scenario(harness)
    except Exception as e:
        return ("raised", type(e).__name__, str(e))
    if isinstance(value, dict):
        return value
    return type(value).__name__


def _clean(h: _Harness) -> Any:
    return h.run("p1", YAML_BASELINE)


def _changes(h: _Harness) -> Any:
    return h.run("p1", CHANGED)


def _partial(h: _Harness) -> Any:
    return h.run("p1", {"Button": "b0"}, is_partial=True)


def _queue_run_with_drift(h: _Harness) -> Any:
    return h.run("q1", CHANGED, branch="trunk-merge/q1", pr_number=None, purpose=RunPurpose.OBSERVE)


def _default_branch_run(h: _Harness) -> Any:
    return h.run(SEED, CHANGED, branch=DEFAULT_BRANCH, pr_number=None, purpose=RunPurpose.OBSERVE)


def _failed_run(h: _Harness) -> Any:
    run = h.create("p1", CHANGED)
    return runs.finish_processing(run.id, error_message="Diff processing failed")


def _finalize_with_commit(h: _Harness) -> Any:
    run = h.run("p1", CHANGED)
    return approvals.finalize_run(run_id=run.id, user_id=h.user_id, approve_all=True)


def _finalize_with_nothing_to_commit(h: _Harness) -> Any:
    run = h.run("p1", CHANGED)
    toleration.mark_snapshot_as_tolerated(run.id, h.snapshot(run, "Button").id, h.user_id, h.team_id)
    return approvals.finalize_run(run_id=run.id, user_id=h.user_id)


def _approve(h: _Harness) -> Any:
    run = h.run("p1", CHANGED)
    return approvals.approve_snapshots(
        run_id=run.id, user_id=h.user_id, approved_snapshots=[{"identifier": "Button", "new_hash": "b1"}]
    )


def _tolerate(h: _Harness) -> Any:
    run = h.run("p1", CHANGED)
    return toleration.mark_snapshot_as_tolerated(run.id, h.snapshot(run, "Button").id, h.user_id, h.team_id)


def _recompute(h: _Harness) -> Any:
    run = h.run("p1", CHANGED)
    QuarantinedIdentifier.objects.create(
        repo=h.repo, team_id=h.team_id, identifier="Button", run_type=RunType.STORYBOOK, reason="flaky"
    )
    return runs.recompute_run(run.id, team_id=h.team_id)


def _quarantine(h: _Harness) -> Any:
    h.run("p1", CHANGED)
    return quarantine.quarantine_identifier(
        repo_id=h.repo.id,
        identifier="Button",
        run_type=RunType.STORYBOOK,
        reason="flaky",
        user_id=h.user_id,
        team_id=h.team_id,
    )


# No wrapping transaction, as in production: a failed statement that a caller catches inside an open
# transaction then aborts that transaction here too, which is the failure this test exists to catch.
@pytest.mark.django_db(transaction=True, databases=PRODUCT_DATABASES)
@pytest.mark.parametrize(
    "scenario",
    [
        _clean,
        _changes,
        _partial,
        _queue_run_with_drift,
        _default_branch_run,
        _failed_run,
        _finalize_with_commit,
        _finalize_with_nothing_to_commit,
        _approve,
        _tolerate,
        _recompute,
        _quarantine,
    ],
    ids=lambda scenario: scenario.__name__.lstrip("_"),
)
def test_shadow_mode_leaves_the_old_flow_as_yaml_mode_runs_it(team, user, mocker, scenario) -> None:
    git = FakeGit(mocker, SEED)
    for sha in ("p1", "q1"):
        git.commit(sha, SEED)
    stored = {content_hash: solid_png(color) for content_hash, color in PICTURES.items()}
    mocker.patch(
        "products.visual_review.backend.storage.ArtifactStorage.read",
        autospec=True,
        side_effect=lambda _storage, content_hash: stored.get(content_hash),
    )
    mocker.patch(
        "products.visual_review.backend.storage.ArtifactStorage.write",
        autospec=True,
        side_effect=lambda _storage, content_hash, content: (
            stored.setdefault(content_hash, content) and f"visual_review/{content_hash}"
        ),
    )
    mocker.patch.object(baselines, "_resolve_baselines_with_merge_base", return_value=(YAML_BASELINE, 0))
    mocks = {
        "commit": mocker.patch.object(baselines, "_commit_baseline_to_github"),
        "rerun": mocker.patch.object(ci_status, "_rerun_github_job", return_value=(True, None)),
        "prompt": mocker.patch.object(comments, "_post_review_prompt_comment"),
    }
    for name, method in _TASKS:
        mocks[name] = mocker.patch.object(getattr(tasks, name), method)

    outcomes = {}
    for external_id, variant in enumerate((YAML, SHADOW, SHADOW_FAILING, SHADOW_LEDGER_BUSY), start=71000):
        harness = _Harness(team.id, user.id, variant, external_id, mocks)
        for mock in mocks.values():
            mock.reset_mock()
        with harness.ledger_faults():
            result = _result(scenario, harness)
        outcomes[variant] = harness.outcome(result)

    for variant in (SHADOW, SHADOW_FAILING, SHADOW_LEDGER_BUSY):
        assert outcomes[variant] == outcomes[YAML], variant
