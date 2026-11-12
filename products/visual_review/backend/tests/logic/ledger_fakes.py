import io

from unittest.mock import MagicMock

from django.utils import timezone

from PIL import Image

from posthog.egress.limiter.policies import Priority

from products.visual_review.backend import diffing
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import BaselineMode, RunPurpose, RunStatus, RunType
from products.visual_review.backend.logic import (
    artifact_store,
    baselines,
    ci_status,
    github_api,
    ledger,
    repos,
    run_queries,
    runs,
)
from products.visual_review.backend.logic.baseline_record import BaselineRecord
from products.visual_review.backend.models import BaselineApproval, Repo, Run

DEFAULT_BRANCH = "master"
SEED = "s0"
RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
CRITICAL = Priority.CRITICAL


def set_baseline_mode(repo: Repo, mode: BaselineMode, *, status_gate: bool | None = None) -> None:
    repo.baseline_mode = mode
    repo.commit_status_gate_enabled = mode == BaselineMode.LEDGER if status_gate is None else status_gate
    repo.save()


def seeded_repo(team_id: int, mode: BaselineMode) -> Repo:
    repo = repos.create_repo(team_id=team_id, repo_external_id=66000, repo_full_name="org/ledger")
    ledger.seed(repo, SEED, {RunType.STORYBOOK: {"Button": "b0", "Card": "c0"}})
    set_baseline_mode(repo, mode)
    return repo


def approve(repo: Repo, pr_number: int, identifier: str, content_hash: str, **fields) -> BaselineApproval:
    base = fields.pop("ledger_base_hash", "b0")
    return BaselineApproval.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=RunType.STORYBOOK,
        pr_number=pr_number,
        identifier=identifier,
        content_hash=content_hash,
        ledger_base_hash=base,
        effective_base_hash=fields.pop("effective_base_hash", base),
        commit_sha=fields.pop("commit_sha", f"head-{pr_number}"),
        approved_at=fields.pop("approved_at", timezone.now()),
        **fields,
    )


def make_record(**fields) -> BaselineRecord:
    return BaselineRecord(
        mode=fields.pop("mode", BaselineMode.LEDGER),
        merge_base_sha=SEED,
        position=0,
        clamped_to_seed=False,
        containment_complete=True,
        overlay=fields.pop("overlay", {}),
        candidate_approval_ids=fields.pop("candidate_approval_ids", ()),
        conflicts={},
        second_candidates={},
        **fields,
    )


class FakeGit:
    def __init__(self, mocker, seed_sha: str) -> None:
        self.parents: dict[str, tuple[str, ...]] = {seed_sha: ()}
        self.subjects: dict[str, str] = {seed_sha: "seed"}
        self.head = seed_sha
        self.pull_requests: dict[int, github_api.PullRequestState] = {}
        self.compare_complete = True
        self.priorities: list[Priority] = []
        mocker.patch.object(
            github_api,
            "default_branch_name",
            side_effect=lambda repo, priority=CRITICAL: self._read(priority, DEFAULT_BRANCH),
        )
        mocker.patch.object(
            github_api,
            "default_branch_head_sha",
            side_effect=lambda repo, priority=CRITICAL: self._read(priority, self.head),
        )
        mocker.patch.object(github_api, "compare_commits", side_effect=self.compare_commits)
        mocker.patch.object(
            github_api,
            "commit_ancestry",
            side_effect=lambda repo, ancestor, head, priority=CRITICAL: self._read(
                priority, ancestor in self.ancestors(head)
            ),
        )
        mocker.patch.object(
            github_api, "commit_contains", side_effect=lambda repo, ancestor, head: ancestor in self.ancestors(head)
        )
        mocker.patch.object(
            github_api,
            "pull_request_state",
            side_effect=lambda repo, number, priority=CRITICAL: self._read(priority, self.pull_requests.get(number)),
        )
        mocker.patch.object(
            github_api,
            "merged_pull_requests_for_commit",
            side_effect=lambda repo, sha, priority=CRITICAL: self._read(priority, []),
        )
        mocker.patch.object(
            github_api,
            "get_github_integration_for_repo",
            return_value=MagicMock(get_default_branch=MagicMock(return_value=DEFAULT_BRANCH)),
        )

    def _read(self, priority: Priority, answer):
        self.priorities.append(priority)
        return answer

    def commit(self, sha: str, *parents: str, subject: str = "") -> str:
        self.parents[sha] = parents
        self.subjects[sha] = subject or sha
        return sha

    def open_pull_request(self, number: int, head_sha: str) -> None:
        self.pull_requests[number] = github_api.PullRequestState(
            state="open", merged=False, merge_commit_sha=None, base_ref=DEFAULT_BRANCH, head_sha=head_sha
        )

    def merge(self, number: int, sha: str) -> str:
        head_sha = self.pull_requests[number].head_sha
        assert head_sha is not None
        self.commit(sha, self.head, head_sha, subject=f"feat: change (#{number})")
        self.head = sha
        self.pull_requests[number] = github_api.PullRequestState(
            state="closed", merged=True, merge_commit_sha=sha, base_ref=DEFAULT_BRANCH, head_sha=head_sha
        )
        return sha

    def ancestors(self, sha: str) -> set[str]:
        seen: set[str] = set()
        pending = [sha]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self.parents.get(current, ()))
        return seen

    def compare_commits(
        self, repo, base: str, head: str, priority: Priority = Priority.CRITICAL
    ) -> github_api.Comparison:
        self.priorities.append(priority)
        base_sha = self.head if base == DEFAULT_BRANCH else base
        base_ancestors = self.ancestors(base_sha)
        head_ancestors = self.ancestors(head)
        merge_base: str | None = base_sha
        while merge_base is not None and merge_base not in head_ancestors:
            first_parents = self.parents.get(merge_base, ())
            merge_base = first_parents[0] if first_parents else None
        return github_api.Comparison(
            merge_base_sha=merge_base,
            commits=tuple(
                github_api.ComparedCommit(sha=sha, parent_shas=self.parents[sha], subject=self.subjects[sha])
                for sha in sorted(head_ancestors - base_ancestors)
            ),
            complete=self.compare_complete,
        )


def solid_png(color: tuple[int, int, int, int]) -> bytes:
    image = Image.new("RGBA", (10, 10), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class LedgerFlow:
    def __init__(self, repo: Repo, mocker) -> None:
        self.repo = repo
        self.stored: dict[str, bytes] = {}
        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            autospec=True,
            side_effect=lambda _storage, content_hash: self.stored.get(content_hash),
        )
        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.write",
            autospec=True,
            side_effect=lambda _storage, content_hash, content: (
                self.stored.setdefault(content_hash, content) and f"visual_review/{content_hash}"
            ),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")
        self.rerun = mocker.patch.object(ci_status, "_rerun_github_job", return_value=(True, None))
        self.commit_to_github = mocker.patch.object(baselines, "_commit_baseline_to_github")

    def picture(self, content_hash: str, color: tuple[int, int, int, int]) -> None:
        self.stored[content_hash] = solid_png(color)
        artifact_store.get_or_create_artifact(self.repo.id, content_hash, f"visual_review/{content_hash}")

    def run(
        self,
        commit_sha: str,
        renders: dict[str, str],
        *,
        branch: str,
        pr_number: int | None = None,
        purpose: RunPurpose = RunPurpose.REVIEW,
    ) -> Run:
        run, _uploads = runs.create_run(
            CreateRunInput(
                repo_id=self.repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha=commit_sha,
                branch=branch,
                pr_number=pr_number,
                purpose=purpose,
                snapshots=[
                    SnapshotManifestItem(identifier=identifier, content_hash=content_hash)
                    for identifier, content_hash in renders.items()
                ],
                metadata={"github_check_run_id": "42", "github_run_id": "777"},
            ),
            team_id=self.repo.team_id,
        )
        completed = runs.complete_run(run.id)
        if completed.status == RunStatus.PROCESSING:
            diffing.process_diffs(run.id)
            runs.finish_processing(run.id)
        return run_queries.get_run_with_snapshots(run.id)


def button_flow(team_id: int, mode: BaselineMode, mocker, *, external_id: int) -> tuple[Repo, FakeGit, LedgerFlow]:
    repo = repos.create_repo(team_id=team_id, repo_external_id=external_id, repo_full_name=f"org/flow-{external_id}")
    ledger.seed(repo, SEED, {RunType.STORYBOOK: {"Button": "b0"}})
    set_baseline_mode(repo, mode)
    git = FakeGit(mocker, SEED)
    flow = LedgerFlow(repo, mocker)
    flow.picture("b0", RED)
    flow.picture("b1", BLUE)
    mocker.patch.object(baselines, "_resolve_baselines_with_merge_base", return_value=({"Button": "b0"}, 0))
    return repo, git, flow
