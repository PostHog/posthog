"""Seed, export and inspect one repo's baseline ledger, and switch which record decides its runs."""

import re
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count

from posthog.models.scoping import team_scope

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.enums import BaselineMode
from products.visual_review.backend.logic import baselines, errors, github_api, ledger
from products.visual_review.backend.management.commands.visual_review_debt_digest import find_repo
from products.visual_review.backend.models import BaselineApproval, BaselineCommit, BaselineEntry, Repo

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# The fallback path key of baseline_file_paths. It is not a run type, so it gets no ledger.
_DEFAULT_PATH_KEY = "default"


def _add_repo_arguments(parser: CommandParser) -> None:
    parser.add_argument("--repo", type=str, required=True, help="Repository as owner/name.")
    parser.add_argument("--team-id", type=int, help="Team that registered the repository.")


class Command(BaseCommand):
    help = "Seed, export and inspect a visual review repo's baseline ledger, and set its baseline mode"

    def add_arguments(self, parser: CommandParser) -> None:
        subcommands = parser.add_subparsers(dest="subcommand", required=True)

        seed = subcommands.add_parser("seed", help="Start the ledger at one default-branch commit.")
        _add_repo_arguments(seed)
        seed.add_argument("--commit", type=str, help="Full SHA. Defaults to the default branch head.")
        seed.add_argument("--replace", action="store_true", help="Replace an existing ledger.")
        seed.add_argument(
            "--run-type",
            action="append",
            dest="run_types",
            help="Seed only this run type. Repeat for more. A run type left out starts with an empty ledger.",
        )
        seed.add_argument(
            "--from-ledger",
            action="store_true",
            help="Start a new position 0 from the ledger at its newest commit, not from the baseline files.",
        )

        export = subcommands.add_parser("export", help="Print the signed baseline file for the ledger's newest commit.")
        _add_repo_arguments(export)
        export.add_argument("--run-type", type=str, required=True)
        export.add_argument("--output", type=str, help="Write to this file instead of stdout.")

        mode = subcommands.add_parser("mode", help="Print or set which record decides the repo's runs.")
        _add_repo_arguments(mode)
        mode.add_argument("--set", type=str, choices=BaselineMode.values, dest="new_mode")

        status_gate = subcommands.add_parser(
            "status-gate", help="Print or set whether the commit status follows the ledger's status rules."
        )
        _add_repo_arguments(status_gate)
        status_gate.add_argument("--set", type=str, choices=["on", "off"], dest="new_status_gate")

        status = subcommands.add_parser("status", help="Summarize the ledger, its approvals and unresolved commits.")
        _add_repo_arguments(status)

    def handle(self, *args: Any, **options: Any) -> None:
        repo = find_repo(options["repo"], options.get("team_id"))
        with team_scope(repo.team_id):
            match options["subcommand"]:
                case "seed":
                    self._seed(repo, options)
                case "export":
                    self._export(repo, options["run_type"], options.get("output"))
                case "mode":
                    self._mode(repo, options.get("new_mode"))
                case "status-gate":
                    self._status_gate(repo, options.get("new_status_gate"))
                case "status":
                    self._status(repo)

    def _commit_to_seed(self, repo: Repo, commit: str | None) -> str:
        if commit is None:
            commit = github_api.default_branch_head_sha(repo)
            if commit is None:
                raise CommandError("GitHub did not return the default branch head. Pass --commit.")
        if not _FULL_SHA_RE.match(commit):
            raise CommandError(f"{commit} is not a full 40-character commit SHA.")
        return commit

    def _seed(self, repo: Repo, options: dict[str, Any]) -> None:
        commit = self._commit_to_seed(repo, options.get("commit"))

        if options["from_ledger"]:
            try:
                count = ledger.seed_from_ledger(repo, commit)
            except errors.BaselineLedgerMissingError as e:
                raise CommandError(str(e)) from e
            self.stdout.write(f"Seeded {count} entries at {commit} from the ledger.")
            return

        configured = [run_type for run_type in (repo.baseline_file_paths or {}) if run_type != _DEFAULT_PATH_KEY]
        run_types = sorted(set(options.get("run_types") or configured))
        if not run_types:
            raise CommandError(
                f"{repo.repo_full_name} names no run type in its baseline file paths. "
                "Name the run types to seed with --run-type."
            )

        github = github_api.get_github_integration_for_repo(repo)
        baselines_by_run_type: dict[str, dict[str, str]] = {}
        for run_type in run_types:
            verified = baselines._resolve_baselines_at_ref(repo, github, run_type, commit)
            # A missing file and a file whose signatures all fail both read as empty. Seeding that
            # would call every story new on the first run that reads the ledger.
            if not verified:
                raise CommandError(
                    f"No verified baseline entries for {run_type} at {commit}. Nothing was seeded. "
                    "A run type without a baseline starts empty: name the run types to seed with --run-type."
                )
            baselines_by_run_type[run_type] = verified

        try:
            ledger.seed(repo, commit, baselines_by_run_type, replace=options["replace"])
        except errors.BaselineLedgerExistsError as e:
            raise CommandError(str(e)) from e
        for run_type in run_types:
            self.stdout.write(f"{run_type}: seeded {len(baselines_by_run_type[run_type])} entries at {commit}")

    def _export(self, repo: Repo, run_type: str, output: str | None) -> None:
        head = ledger.cursor(repo.id)
        if head is None:
            raise CommandError(f"{repo.repo_full_name} has no baseline ledger.")
        hashes = ledger.ledger_at(repo.id, run_type, head.position)
        ever_held = BaselineEntry.objects.using(WRITER_DB).filter(repo_id=repo.id, run_type=run_type).exists()
        if not ever_held:
            raise CommandError(f"The ledger has no entries for {run_type}.")

        updates = [{"identifier": identifier, "new_hash": content_hash} for identifier, content_hash in hashes.items()]
        content = baselines._build_snapshots_yaml(repo, current_baselines={}, updates=updates)
        if output is None:
            self.stdout.write(content, ending="")
            return
        Path(output).write_text(content)
        self.stdout.write(f"Wrote {len(hashes)} entries for {run_type} at {head.commit_sha} to {output}")

    def _mode(self, repo: Repo, new_mode: str | None) -> None:
        if new_mode is None:
            self.stdout.write(repo.baseline_mode)
            return
        try:
            ledger.set_baseline_mode(repo, BaselineMode(new_mode))
        except (errors.BaselineLedgerMissingError, errors.CommitStatusGateError) as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{repo.repo_full_name} is now in {new_mode} mode.")

    def _status_gate(self, repo: Repo, new_status_gate: str | None) -> None:
        if new_status_gate is None:
            self.stdout.write("on" if repo.commit_status_gate_enabled else "off")
            return
        try:
            ledger.set_commit_status_gate(repo, new_status_gate == "on")
        except errors.CommitStatusGateError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"The commit status gate of {repo.repo_full_name} is now {new_status_gate}.")

    def _status(self, repo: Repo) -> None:
        self.stdout.write(f"Mode: {repo.baseline_mode}")
        self.stdout.write(f"Commit status gate: {'on' if repo.commit_status_gate_enabled else 'off'}")
        head = ledger.cursor(repo.id)
        if head is None:
            self.stdout.write("No ledger.")
            return
        self.stdout.write(f"Cursor: position {head.position}, commit {head.commit_sha}")

        entry_counts = (
            BaselineEntry.objects.using(WRITER_DB)
            .filter(repo_id=repo.id)
            .values_list("run_type")
            .annotate(count=Count("id"))
            .order_by("run_type")
        )
        for run_type, count in entry_counts:
            self.stdout.write(f"Entries for {run_type}: {count}")

        approval_counts = (
            BaselineApproval.objects.using(WRITER_DB)
            .filter(repo_id=repo.id)
            .values_list("state")
            .annotate(count=Count("id"))
            .order_by("state")
        )
        for state, count in approval_counts:
            self.stdout.write(f"Approvals {state}: {count}")

        unresolved = (
            BaselineCommit.objects.using(WRITER_DB).filter(repo_id=repo.id, resolved=False).order_by("position")
        )
        for commit in unresolved:
            self.stdout.write(
                f"Unresolved: position {commit.position}, commit {commit.commit_sha}, PR #{commit.pr_number}"
            )
