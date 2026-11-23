from io import StringIO

import pytest

from django.core.management import call_command
from django.db import transaction

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import BaselineLedgerAdoptionItem
from products.visual_review.backend.facade.enums import (
    BaselineEntrySource,
    BaselineMode,
    RunPurpose,
    RunStatus,
    RunType,
)
from products.visual_review.backend.logic import errors, ledger, ledger_adopt, repos
from products.visual_review.backend.models import BaselineEntry, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES
from products.visual_review.backend.tests.logic.ledger_fakes import DEFAULT_BRANCH, FakeGit, approve, set_baseline_mode

B0, B1 = "b0", "b1"
C0, C1, C2 = "c0", "c1", "c2"


def _run(repo: Repo, commit_sha: str, renders: dict[str, str], **fields) -> Run:
    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=RunType.STORYBOOK,
        commit_sha=commit_sha,
        branch=fields.pop("branch", DEFAULT_BRANCH),
        purpose=fields.pop("purpose", RunPurpose.OBSERVE),
        status=RunStatus.COMPLETED,
        **fields,
    )
    for identifier, current_hash in renders.items():
        RunSnapshot.objects.create(run=run, team_id=repo.team_id, identifier=identifier, current_hash=current_hash)
    return run


def _adopted_entries(repo: Repo) -> set[tuple]:
    return set(
        BaselineEntry.objects.filter(repo=repo, source=BaselineEntrySource.REPAIR).values_list(
            "position", "commit_sha", "identifier", "previous_hash", "content_hash"
        )
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestLedgerAdopt:
    @pytest.fixture
    def repo(self, team, mocker) -> Repo:
        repo = repos.create_repo(team_id=team.id, repo_external_id=88890, repo_full_name="org/adopt-renders")
        ledger.seed(repo, "s0", {RunType.STORYBOOK: {"Button": B0, "Card": C0}})
        set_baseline_mode(repo, BaselineMode.LEDGER)
        FakeGit(mocker, "s0")
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(repo.id)
            for position, sha in enumerate(("s1", "s2", "s3"), start=1):
                ledger.append_commit(repo, position=position, commit_sha=sha, pr_number=10 + position)
            ledger.append_entry(
                repo,
                run_type=RunType.STORYBOOK,
                identifier="Card",
                content_hash=C1,
                previous_hash=C0,
                position=2,
                commit_sha="s2",
                source=BaselineEntrySource.MERGE,
                pr_number=12,
            )
            ledger.append_commit(repo, position=4, commit_sha="s4", pr_number=14, resolved=False)
        return repo

    @pytest.mark.parametrize(
        ("mode", "commit_sha", "run_fields", "identifiers", "message"),
        [
            pytest.param(
                BaselineMode.SHADOW,
                "s3",
                {},
                ["Button"],
                "in shadow mode. Adopting renders only runs in ledger mode",
                id="shadow_mode",
            ),
            pytest.param(BaselineMode.LEDGER, "s3", {"is_partial": True}, ["Button"], "is a partial run", id="partial"),
            pytest.param(
                BaselineMode.LEDGER,
                "s3",
                {"purpose": RunPurpose.REVIEW, "pr_number": 5, "branch": "feature"},
                ["Button"],
                "not a default-branch run: it is a review run of PR #5",
                id="pull_request_run",
            ),
            pytest.param(
                BaselineMode.LEDGER,
                "s3",
                {"branch": "feature"},
                ["Button"],
                "ran on feature, not on the default branch master",
                id="observe_run_off_the_default_branch",
            ),
            pytest.param(
                BaselineMode.LEDGER,
                "s4",
                {},
                ["Button"],
                "s4 of run .* is not a resolved commit of the ledger",
                id="unresolved_commit",
            ),
            pytest.param(
                BaselineMode.LEDGER,
                "s3",
                {},
                ["Button", "Gone", "Nope"],
                "did not render Gone, Nope",
                id="identifiers_without_a_render",
            ),
            pytest.param(
                BaselineMode.LEDGER,
                "s1",
                {},
                ["Button", "Card"],
                "changed Card after position 1 of run .* Pick a newer full default-branch run",
                id="ledger_changed_after_the_run",
            ),
        ],
    )
    def test_refuses_and_writes_nothing(self, repo, mode, commit_sha, run_fields, identifiers, message) -> None:
        set_baseline_mode(repo, mode)
        run = _run(repo, commit_sha, {"Button": B1, "Card": C2, "Gone": ""}, **run_fields)
        entries_before = BaselineEntry.objects.filter(repo=repo).count()

        with pytest.raises(errors.BaselineAdoptionError, match=message):
            ledger_adopt.adopt_renders(repo, RunType.STORYBOOK, run.id, identifiers)

        assert BaselineEntry.objects.filter(repo=repo).count() == entries_before

    def test_apply_appends_at_the_cursor_and_a_second_apply_writes_nothing(self, repo) -> None:
        approve(repo, 7, "Button", "b2", ledger_base_hash=B0)
        # Card changed after s1, and the run already renders what the ledger holds at the cursor.
        run = _run(repo, "s1", {"Button": B1, "Card": C1})

        plan = ledger_adopt.adopt_renders(repo, RunType.STORYBOOK, run.id, ["Card", "Button"])

        assert plan.items == (
            BaselineLedgerAdoptionItem(identifier="Button", ledger_hash=B0, render_hash=B1, open_approvals=1),
            BaselineLedgerAdoptionItem(identifier="Card", ledger_hash=C1, render_hash=C1, open_approvals=0),
        )
        assert _adopted_entries(repo) == {(3, "s3", "Button", B0, B1)}
        assert ledger.ledger_at(repo.id, RunType.STORYBOOK, 3) == {"Button": B1, "Card": C1}

        again = ledger_adopt.adopt_renders(repo, RunType.STORYBOOK, run.id, ["Button", "Card"])

        assert again.to_append == ()
        assert _adopted_entries(repo) == {(3, "s3", "Button", B0, B1)}

    def test_command_dry_run_prints_the_plan_and_apply_writes(self, repo) -> None:
        run = _run(repo, "s3", {"Button": B1, "Card": C1})
        args = (
            "visual_review_baseline_ledger",
            "adopt-renders",
            "--repo",
            repo.repo_full_name,
            "--run-type",
            RunType.STORYBOOK,
            "--run",
            str(run.id),
            "--identifier",
            "Button",
            "--identifier",
            "Card",
        )

        dry_run = StringIO()
        call_command(*args, stdout=dry_run)

        assert _adopted_entries(repo) == set()
        lines = [line.split() for line in dry_run.getvalue().splitlines()]
        assert ["Button", B0, B1, "append", "0"] in lines
        assert ["Card", C1, C1, "already", "matches", "0"] in lines
        assert "Dry run, nothing was written." in dry_run.getvalue()

        applied = StringIO()
        call_command(*args, "--apply", stdout=applied)

        assert "Wrote 1 entries." in applied.getvalue()
        assert _adopted_entries(repo) == {(3, "s3", "Button", B0, B1)}
