from io import StringIO

import pytest
from unittest.mock import MagicMock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

import yaml

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import BaselineEntrySource, BaselineMode, RunType
from products.visual_review.backend.logic import errors, github_api, ledger, repos
from products.visual_review.backend.models import BaselineApproval, BaselineEntry, Repo
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES

_SEED_SHA = "a" * 40
_NEXT_SHA = "b" * 40
_RESEED_SHA = "c" * 40
# Signed baseline files only accept 64-character hex content hashes.
_BUTTON_0 = "0" * 64
_BUTTON_1 = "1" * 64
_CARD_0 = "2" * 64


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestLedger:
    @pytest.fixture
    def repo(self, team) -> Repo:
        return repos.create_repo(team_id=team.id, repo_external_id=77777, repo_full_name="org/ledger")

    def _append(self, repo: Repo, identifier: str, content_hash: str, position: int) -> None:
        ledger.append_entry(
            repo,
            run_type=RunType.STORYBOOK,
            identifier=identifier,
            content_hash=content_hash,
            previous_hash="",
            position=position,
            commit_sha=_NEXT_SHA,
            source=BaselineEntrySource.MERGE,
        )

    def _approval(self, repo: Repo, **fields: str) -> BaselineApproval:
        return BaselineApproval.objects.create(
            repo=repo,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            pr_number=7,
            identifier="Button",
            commit_sha=_NEXT_SHA,
            approved_at=timezone.now(),
            **fields,
        )

    def test_ledger_at_reads_the_newest_entry_at_or_below_the_position(self, repo) -> None:
        self._append(repo, "Moved", "moved-0", 0)
        self._append(repo, "Moved", "moved-2", 2)
        self._append(repo, "Moved", "moved-5", 5)
        self._append(repo, "Tied", "tied-first", 1)
        self._append(repo, "Tied", "tied-second", 1)
        self._append(repo, "Removed", "removed-0", 0)
        self._append(repo, "Removed", "", 2)

        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 1) == {
            "Moved": "moved-0",
            "Tied": "tied-second",
            "Removed": "removed-0",
        }
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 3) == {"Moved": "moved-2", "Tied": "tied-second"}
        assert ledger.hashes_at(repo.id, RunType.STORYBOOK, ["Moved", "Removed", "Unknown"], 3) == {"Moved": "moved-2"}
        assert ledger.ledger_at(repo.id, RunType.PLAYWRIGHT, 3) == {}

    def test_seed_refuses_a_second_seed_and_replace_keeps_approvals(self, repo) -> None:
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": "button-0", "Card": "card-0"}})
        approval = self._approval(repo, content_hash="button-1")

        with pytest.raises(errors.BaselineLedgerExistsError):
            ledger.seed(repo, _RESEED_SHA, {RunType.STORYBOOK: {"Button": "button-9"}})

        count = ledger.seed(repo, _RESEED_SHA, {RunType.STORYBOOK: {"Button": "button-9"}}, replace=True)

        assert count == 1
        head = ledger.cursor(repo.id)
        assert head is not None and head.commit_sha == _RESEED_SHA
        assert ledger.position_of(repo.id, _SEED_SHA) is None
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0) == {"Button": "button-9"}
        assert BaselineApproval.objects.filter(id=approval.id).exists()

    def test_seed_from_ledger_carries_the_ledger_at_the_cursor_without_removals(self, repo) -> None:
        ledger.seed(
            repo,
            _SEED_SHA,
            {RunType.STORYBOOK: {"Button": "button-0", "Card": "card-0", "Gone": "gone-0"}, RunType.PLAYWRIGHT: {}},
        )
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            ledger.append_commit(repo, position=1, commit_sha=_NEXT_SHA, pr_number=7)
            self._append(repo, "Button", "button-1", 1)
            self._append(repo, "Gone", "", 1)

        count = ledger.seed_from_ledger(repo, _RESEED_SHA)

        assert count == 2
        head = ledger.cursor(repo.id)
        assert head is not None and (head.position, head.commit_sha) == (0, _RESEED_SHA)
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0) == {"Button": "button-1", "Card": "card-0"}
        assert set(BaselineEntry.objects.filter(repo=repo).values_list("source", "content_hash")) == {
            (BaselineEntrySource.SEED, "button-1"),
            (BaselineEntrySource.SEED, "card-0"),
        }

    def test_mode_set_refuses_a_ledger_mode_without_a_ledger(self, repo) -> None:
        with pytest.raises(CommandError, match="seed"):
            call_command("visual_review_baseline_ledger", "mode", "--repo", repo.repo_full_name, "--set", "shadow")

        repo.refresh_from_db()
        assert repo.baseline_mode == BaselineMode.YAML

    def test_ledger_mode_and_the_commit_status_gate_go_together(self, repo) -> None:
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": _BUTTON_0}})
        command = ("visual_review_baseline_ledger", "--repo", repo.repo_full_name)

        with pytest.raises(CommandError, match="status-gate"):
            call_command(command[0], "mode", *command[1:], "--set", "ledger")
        call_command(command[0], "status-gate", *command[1:], "--set", "on", stdout=StringIO())
        call_command(command[0], "mode", *command[1:], "--set", "ledger", stdout=StringIO())
        with pytest.raises(CommandError, match="shadow first"):
            call_command(command[0], "status-gate", *command[1:], "--set", "off")

        repo.refresh_from_db()
        assert (repo.baseline_mode, repo.commit_status_gate_enabled) == (BaselineMode.LEDGER, True)
        output = StringIO()
        call_command(command[0], "status", *command[1:], stdout=output)
        assert "Commit status gate: on" in output.getvalue()

    def _export_storybook(self, repo: Repo) -> dict:
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

    def _github_serves(self, mocker, files: dict[str, dict]) -> None:
        mocker.patch.object(github_api, "get_github_integration_for_repo", return_value=MagicMock())
        mocker.patch.object(
            github_api,
            "_fetch_baseline_file",
            side_effect=lambda github, repo_full_name, file_path, ref: (files.get(file_path, {}), "blob"),
        )

    def test_export_round_trips_through_the_seed_command(self, repo, mocker) -> None:
        repo.baseline_file_paths = {RunType.STORYBOOK: ".storybook.yml"}
        repo.save()
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": _BUTTON_0, "Card": _CARD_0}})
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            ledger.append_commit(repo, position=1, commit_sha=_NEXT_SHA, pr_number=7)
            self._append(repo, "Button", _BUTTON_1, 1)
            self._append(repo, "Card", "", 1)
        self._github_serves(mocker, {".storybook.yml": self._export_storybook(repo)})

        call_command(
            "visual_review_baseline_ledger",
            "seed",
            "--repo",
            repo.repo_full_name,
            "--commit",
            _RESEED_SHA,
            "--replace",
            stdout=StringIO(),
        )

        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0) == {"Button": _BUTTON_1}

    def test_export_writes_an_empty_file_once_every_snapshot_is_removed(self, repo) -> None:
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": _BUTTON_0}})
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            ledger.append_commit(repo, position=1, commit_sha=_NEXT_SHA, pr_number=7)
            self._append(repo, "Button", "", 1)

        assert self._export_storybook(repo) == {}
        with pytest.raises(CommandError, match="no entries for playwright"):
            call_command(
                "visual_review_baseline_ledger",
                "export",
                "--repo",
                repo.repo_full_name,
                "--run-type",
                RunType.PLAYWRIGHT,
                stdout=StringIO(),
            )

    def test_seed_with_run_type_skips_a_run_type_whose_file_is_empty(self, repo, mocker) -> None:
        repo.baseline_file_paths = {RunType.STORYBOOK: ".storybook.yml", RunType.PLAYWRIGHT: ".playwright.yml"}
        repo.save()
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": _BUTTON_0}})
        self._github_serves(mocker, {".storybook.yml": self._export_storybook(repo)})
        seed_args = [
            "visual_review_baseline_ledger",
            "seed",
            "--repo",
            repo.repo_full_name,
            "--commit",
            _RESEED_SHA,
            "--replace",
        ]

        with pytest.raises(CommandError, match="No verified baseline entries for playwright"):
            call_command(*seed_args, stdout=StringIO())
        call_command(*seed_args, "--run-type", RunType.STORYBOOK, stdout=StringIO())

        head = ledger.cursor(repo.id)
        assert head is not None and head.commit_sha == _RESEED_SHA
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0) == {"Button": _BUTTON_0}
        assert ledger.ledger_at(repo.id, RunType.PLAYWRIGHT, 0) == {}

    @pytest.mark.parametrize(
        "baseline_file_paths, served_path",
        [
            ({}, ".snapshots.yml"),
            ({"default": ".storybook.yml"}, ".storybook.yml"),
        ],
    )
    def test_seed_reads_a_named_run_type_through_the_fallback_path(
        self, repo, mocker, baseline_file_paths, served_path
    ) -> None:
        ledger.seed(repo, _SEED_SHA, {RunType.STORYBOOK: {"Button": _BUTTON_0}})
        repo.baseline_file_paths = baseline_file_paths
        repo.save()
        self._github_serves(mocker, {served_path: self._export_storybook(repo)})
        seed_args = [
            "visual_review_baseline_ledger",
            "seed",
            "--repo",
            repo.repo_full_name,
            "--commit",
            _RESEED_SHA,
            "--replace",
        ]

        with pytest.raises(CommandError, match="--run-type"):
            call_command(*seed_args, stdout=StringIO())
        call_command(*seed_args, "--run-type", RunType.STORYBOOK, stdout=StringIO())

        head = ledger.cursor(repo.id)
        assert head is not None and head.commit_sha == _RESEED_SHA
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 0) == {"Button": _BUTTON_0}
