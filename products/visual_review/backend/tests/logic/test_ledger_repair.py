import hashlib
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
from products.visual_review.backend.logic import baselines, github_api, ledger, ledger_advance, ledger_repair, repos
from products.visual_review.backend.models import BaselineApproval, BaselineEntry, Repo
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import FakeGit, approve, set_baseline_mode

# Signed baseline files only accept 64-character hex content hashes.
B0, B1, B2 = "0" * 64, "1" * 64, "2" * 64
C0, C1, C2, C3 = "3" * 64, "4" * 64, "5" * 64, "6" * 64
G0 = "7" * 64


def _signed(repo: Repo, hashes: dict[str, str]) -> dict:
    updates = [{"identifier": identifier, "new_hash": content_hash} for identifier, content_hash in hashes.items()]
    return yaml.safe_load(baselines._build_snapshots_yaml(repo, current_baselines={}, updates=updates))["snapshots"]


class _FakeBaselineFile:
    def __init__(self, mocker, repo: Repo) -> None:
        self.repo = repo
        self.history: list[str] = []
        self.files: dict[str, dict] = {}
        self.priorities: set[Priority] = set()
        self.integration = MagicMock()
        # GitHub answers 404 for every read, as after a lost access.
        self.missing = False
        self.real_blob_lookup = False
        self._real_file_blob_sha = github_api.file_blob_sha
        mocker.patch.object(github_api, "get_github_integration_for_repo", side_effect=self._integration)
        mocker.patch.object(github_api, "file_blob_sha", side_effect=self._file_blob_sha)
        mocker.patch.object(github_api, "_fetch_baseline_file", side_effect=self._fetch_baseline_file)

    def commit(self, sha: str, hashes: dict[str, str] | None = None) -> None:
        self.history.append(sha)
        if hashes is not None:
            self.files[sha] = _signed(self.repo, hashes)

    def _file_at(self, sha: str) -> dict:
        reachable = self.history[: self.history.index(sha) + 1]
        return next(self.files[changed] for changed in reversed(reachable) if changed in self.files)

    def _fetch_baseline_file(self, github, repo_full_name: str, file_path: str, ref: str) -> tuple[dict, str | None]:
        if self.missing:
            return {}, None
        return self._file_at(ref), "blob"

    def _file_blob_sha(self, repo: Repo, path: str, ref: str, priority: Priority = Priority.CRITICAL) -> str:
        self.priorities.add(priority)
        if self.real_blob_lookup:
            return self._real_file_blob_sha(repo, path, ref, priority)
        if self.missing:
            return ""
        return hashlib.sha1(yaml.safe_dump(self._file_at(ref)).encode()).hexdigest()

    def _integration(self, repo: Repo, priority: Priority = Priority.CRITICAL) -> MagicMock:
        self.priorities.add(priority)
        return self.integration


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


def _repair_entries(repo: Repo) -> set[tuple]:
    return set(
        BaselineEntry.objects.filter(repo=repo, source=BaselineEntrySource.REPAIR, approval__isnull=True).values_list(
            "position", "commit_sha", "pr_number", "identifier", "previous_hash", "content_hash"
        )
    )


# Per position: the commit, its pull request, the merge entries the ledger recorded, and the
# baseline file when the commit changed it.
_History = list[tuple[str, int | None, dict[str, str], dict[str, str] | None]]
_HISTORY: _History = [
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

    def _record(self, baseline_file: _FakeBaselineFile, seed: dict[str, str], history: _History) -> Repo:
        repo = baseline_file.repo
        ledger.seed(repo, "s0", {RunType.STORYBOOK: seed})
        set_baseline_mode(repo, BaselineMode.SHADOW)
        baseline_file.commit("s0", seed)
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            for position, (sha, pr_number, merged, file_hashes) in enumerate(history, start=1):
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

    @pytest.fixture
    def repo(self, baseline_file) -> Repo:
        return self._record(baseline_file, _FILE_AT[0], _HISTORY)

    def test_a_dry_run_prints_the_plan_and_writes_nothing(self, repo, baseline_file, mocker) -> None:
        mocker.patch.object(ledger_repair, "PROGRESS_INTERVAL", 2)
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        output = _repair(repo)

        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before
        assert f"  Gone: {G0} -> removed (removal)" in output
        assert "3 entries at 3 positions for 3 identifiers" in output
        assert "Drift at the cursor: 2 identifiers before, 0 after" in output
        assert "Read the baseline file at 4 of 5 positions" in output
        assert "Dry run" in output
        assert baseline_file.priorities == {Priority.BATCH}

    def test_apply_makes_the_ledger_equal_the_baseline_file_at_every_position(self, repo) -> None:
        output = _repair(repo, "--apply")

        assert "Wrote 3 entries." in output
        assert {position: ledger.ledger_at(repo.id, RunType.STORYBOOK, position) for position in _FILE_AT} == _FILE_AT
        assert _repair_entries(repo) == {
            (1, "s1", 11, "Button", B0, B1),
            (2, "s2", 12, "Card", C1, C2),
            (3, "s3", 13, "Gone", G0, ""),
        }
        assert _export(repo) == _signed(repo, _FILE_AT[5])

    @pytest.mark.parametrize(
        ("history", "file_at", "expected_entries"),
        [
            pytest.param(
                [("t1", 21, {}, {"Button": B1}), ("t2", 22, {}, None), ("t3", 23, {}, {"Button": B0})],
                [{"Button": B0}, {"Button": B1}, {"Button": B1}, {"Button": B0}],
                {(1, "t1", 21, "Button", B0, B1), (3, "t3", 23, "Button", B1, B0)},
                id="two_changes_that_cancel_out",
            ),
            pytest.param(
                [("t1", 21, {}, None), ("t2", 22, {}, None), ("t3", 23, {}, {"Button": B1})],
                [{"Button": B0}, {"Button": B0}, {"Button": B0}, {"Button": B1}],
                {(3, "t3", 23, "Button", B0, B1)},
                id="a_change_at_the_cursor",
            ),
        ],
    )
    def test_apply_repairs_every_change_the_walk_finds(self, baseline_file, history, file_at, expected_entries) -> None:
        repo = self._record(baseline_file, {"Button": B0}, history)

        _repair(repo, "--apply")

        assert _repair_entries(repo) == expected_entries
        assert [ledger.ledger_at(repo.id, RunType.STORYBOOK, position) for position in range(len(file_at))] == file_at

    def test_a_baseline_file_github_does_not_find_stops_the_repair(self, repo, baseline_file) -> None:
        baseline_file.missing = True
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        for args in ((), ("--apply",)):
            with pytest.raises(CommandError, match="did not find .* at position 0, commit s0"):
                _repair(repo, *args)

        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before

    @pytest.mark.parametrize(
        ("path", "listing"),
        [
            pytest.param("../snapshots.yml", [], id="dot_segment_in_the_path"),
            pytest.param("frontend/snapshots.yml", {"message": "not a listing"}, id="malformed_listing"),
        ],
    )
    def test_a_bad_path_or_listing_ends_as_a_repair_error(self, repo, baseline_file, path, listing) -> None:
        repo.baseline_file_paths = {RunType.STORYBOOK: path}
        repo.save()
        baseline_file.real_blob_lookup = True
        baseline_file.integration.api_request.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value=listing)
        )

        with pytest.raises(CommandError, match="could not be read"):
            _repair(repo)

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
