from datetime import UTC, datetime
from io import StringIO

import pytest
from unittest.mock import MagicMock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

import yaml

from posthog.egress.limiter.policies import Priority

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import (
    BaselineApprovalState,
    BaselineEntrySource,
    BaselineMode,
    RunType,
)
from products.visual_review.backend.logic import baselines, github_api, ledger, ledger_advance, repos
from products.visual_review.backend.models import BaselineApproval, BaselineEntry, Repo
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import FakeGit, approve, set_baseline_mode

# Signed baseline files only accept 64-character hex content hashes.
B0, B1, B2 = "0" * 64, "1" * 64, "2" * 64
C0, C1, C2, C3 = "3" * 64, "4" * 64, "5" * 64, "6" * 64
G0 = "7" * 64
SEED_DATE = datetime(2026, 1, 5, tzinfo=UTC)


def _signed(repo: Repo, hashes: dict[str, str]) -> dict:
    updates = [{"identifier": identifier, "new_hash": content_hash} for identifier, content_hash in hashes.items()]
    return yaml.safe_load(baselines._build_snapshots_yaml(repo, current_baselines={}, updates=updates))["snapshots"]


class _FakeBaselineFile:
    def __init__(self, mocker, repo: Repo) -> None:
        self.repo = repo
        self.history: list[str] = []
        self.files: dict[str, dict] = {}
        self.unlisted: set[str] = set()
        mocker.patch.object(github_api, "get_github_integration_for_repo", return_value=MagicMock())
        mocker.patch.object(github_api, "commit_date", return_value=SEED_DATE)
        mocker.patch.object(github_api, "commits_touching_path", side_effect=self._commits_touching_path)
        mocker.patch.object(
            github_api,
            "_fetch_baseline_file",
            side_effect=lambda github, repo_full_name, file_path, ref: (self._file_at(ref), "blob"),
        )

    def commit(self, sha: str, hashes: dict[str, str] | None = None) -> None:
        self.history.append(sha)
        if hashes is not None:
            self.files[sha] = _signed(self.repo, hashes)

    def _file_at(self, sha: str) -> dict:
        reachable = self.history[: self.history.index(sha) + 1]
        return next(self.files[changed] for changed in reversed(reachable) if changed in self.files)

    def _commits_touching_path(
        self, repo: Repo, path: str, head_sha: str, since: datetime, priority: Priority = Priority.CRITICAL
    ) -> list[str]:
        reachable = self.history[: self.history.index(head_sha) + 1]
        return [sha for sha in reversed(reachable) if sha in self.files and sha not in self.unlisted]


def _repair(repo: Repo, *args: str) -> str:
    out = StringIO()
    call_command(
        "visual_review_baseline_ledger",
        "repair",
        "--repo",
        repo.repo_full_name,
        "--run-type",
        RunType.STORYBOOK,
        *args,
        stdout=out,
    )
    return out.getvalue()


def _export(repo: Repo) -> dict:
    out = StringIO()
    call_command(
        "visual_review_baseline_ledger",
        "export",
        "--repo",
        repo.repo_full_name,
        "--run-type",
        RunType.STORYBOOK,
        stdout=out,
    )
    return yaml.safe_load(out.getvalue())["snapshots"]


# Per position: the commit, its pull request, the merge entries the ledger recorded, and the
# baseline file when the commit changed it.
_HISTORY: list[tuple[str, int | None, dict[str, str], dict[str, str] | None]] = [
    ("s1", 11, {}, {"Button": B1, "Card": C0, "Gone": G0}),
    ("s2", 12, {"Card": C1}, {"Button": B1, "Card": C2, "Gone": G0}),
    ("s3", 13, {}, {"Button": B1, "Card": C2}),
    ("s4", 14, {"Card": C3}, {"Button": B1, "Card": C3}),
    ("s5", None, {}, None),
]
_FILE_AT = {
    0: {"Button": B0, "Card": C0, "Gone": G0},
    1: {"Button": B1, "Card": C0, "Gone": G0},
    2: {"Button": B1, "Card": C2, "Gone": G0},
    3: {"Button": B1, "Card": C2},
    4: {"Button": B1, "Card": C3},
    5: {"Button": B1, "Card": C3},
}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestLedgerRepair:
    @pytest.fixture
    def baseline_file(self, team, mocker) -> _FakeBaselineFile:
        repo = repos.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/repair")
        return _FakeBaselineFile(mocker, repo)

    @pytest.fixture
    def repo(self, baseline_file) -> Repo:
        repo = baseline_file.repo
        ledger.seed(repo, "s0", {RunType.STORYBOOK: _FILE_AT[0]})
        set_baseline_mode(repo, BaselineMode.SHADOW)
        baseline_file.commit("s0", _FILE_AT[0])
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            for position, (sha, pr_number, merged, file_hashes) in enumerate(_HISTORY, start=1):
                ledger.append_commit(repo, position=position, commit_sha=sha, pr_number=pr_number)
                for identifier, content_hash in merged.items():
                    ledger.append_entry(
                        repo,
                        run_type=RunType.STORYBOOK,
                        identifier=identifier,
                        content_hash=content_hash,
                        previous_hash="",
                        position=position,
                        commit_sha=sha,
                        source=BaselineEntrySource.MERGE,
                        pr_number=pr_number,
                    )
                baseline_file.commit(sha, file_hashes)
        return repo

    def test_a_dry_run_prints_the_plan_and_writes_nothing(self, repo) -> None:
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        output = _repair(repo)

        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before
        assert f"  Gone: {G0} -> removed (removal)" in output
        assert "3 entries at 3 positions for 3 identifiers" in output
        assert "Drift at the cursor: 2 identifiers before, 0 after" in output
        assert "Dry run" in output

    def test_apply_makes_the_ledger_equal_the_baseline_file_at_every_position(self, repo) -> None:
        output = _repair(repo, "--apply")

        assert "Wrote 3 entries." in output
        assert {position: ledger.ledger_at(repo.id, RunType.STORYBOOK, position) for position in _FILE_AT} == _FILE_AT
        repair_entries = BaselineEntry.objects.filter(
            repo=repo, source=BaselineEntrySource.REPAIR, approval__isnull=True
        ).values_list("position", "commit_sha", "pr_number", "identifier", "previous_hash", "content_hash")
        assert set(repair_entries) == {
            (1, "s1", 11, "Button", B0, B1),
            (2, "s2", 12, "Card", C1, C2),
            (3, "s3", 13, "Gone", G0, ""),
        }
        assert _export(repo) == _signed(repo, _FILE_AT[5])

    def test_a_change_github_does_not_list_shows_as_drift_and_blocks_the_apply(self, repo, baseline_file) -> None:
        baseline_file.unlisted.add("s4")
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        output = _repair(repo)
        with pytest.raises(CommandError, match="1 identifiers would still differ"):
            _repair(repo, "--apply")

        assert "  Still drifted: Card" in output
        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before

    def test_a_second_apply_plans_nothing(self, repo) -> None:
        _repair(repo, "--apply")
        entries_after_first = BaselineEntry.objects.filter(repo=repo).count()

        output = _repair(repo, "--apply")

        assert "Wrote 0 entries." in output
        assert BaselineEntry.objects.filter(repo=repo).count() == entries_after_first

    @pytest.mark.parametrize(
        ("mode", "message"),
        [
            (BaselineMode.LEDGER, "ledger mode, where the ledger decides"),
            (BaselineMode.YAML, "yaml mode. Repair only runs in shadow mode"),
        ],
    )
    def test_refuses_outside_shadow_mode(self, repo, mode, message) -> None:
        set_baseline_mode(repo, mode)
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        with pytest.raises(CommandError, match=message):
            _repair(repo, "--apply")

        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_open_approvals_land_after_a_repair_of_their_base(team, mocker) -> None:
    repo = repos.create_repo(team_id=team.id, repo_external_id=88889, repo_full_name="org/repair-landing")
    ledger.seed(repo, "s0", {RunType.STORYBOOK: {"Button": B0, "Card": C0}})
    set_baseline_mode(repo, BaselineMode.SHADOW)
    git = FakeGit(mocker, "s0")
    baseline_file = _FakeBaselineFile(mocker, repo)
    baseline_file.commit("s0", {"Button": B0, "Card": C0})
    git.commit("s1", "s0", subject="revert: card")
    git.head = "s1"
    baseline_file.commit("s1", {"Button": B0, "Card": C1})
    ledger_advance.advance(repo)

    _repair(repo, "--apply")
    other_identifier = approve(repo, 7, "Button", B1, ledger_base_hash=B0)
    # Made on a run whose file already held the change the ledger missed.
    same_identifier = approve(repo, 8, "Card", C2, ledger_base_hash=C0, effective_base_hash=C1)
    for pr_number, merge_sha in ((7, "s2"), (8, "s3")):
        git.commit(f"head-{pr_number}", git.head)
        git.open_pull_request(pr_number, f"head-{pr_number}")
        git.merge(pr_number, merge_sha)
    ledger_advance.advance(repo)

    states = dict(
        BaselineApproval.objects.filter(id__in=[other_identifier.id, same_identifier.id]).values_list("id", "state")
    )
    assert states == {
        other_identifier.id: BaselineApprovalState.PROMOTED,
        same_identifier.id: BaselineApprovalState.PROMOTED,
    }
    assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 3) == {"Button": B1, "Card": C2}
