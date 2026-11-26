"""Seed, repair, adopt renders, export and inspect one repo's baseline ledger, and switch which record decides its runs."""

import re
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.scoping import team_scope

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade import api, contracts
from products.visual_review.backend.facade.enums import (
    BaselineMode,
    ReviewState,
    RunGate,
    RunPurpose,
    RunStatus,
    SnapshotResult,
)
from products.visual_review.backend.logic import baselines, commit_status, errors, github_api, ledger
from products.visual_review.backend.management.commands.visual_review_debt_digest import find_repo
from products.visual_review.backend.models import (
    BaselineApproval,
    BaselineCommit,
    BaselineEntry,
    Repo,
    Run,
    RunSnapshot,
)

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# The fallback path key of baseline_file_paths. It is not a run type, so it gets no ledger.
_DEFAULT_PATH_KEY = "default"

_MAX_LISTED_PULL_REQUESTS = 50

_COUNT_RE = re.compile(r"\d+")


@frozen
class _Heads:
    heads: list[github_api.BranchHead]
    # Heads of pull requests that target another branch than the default one, and of none that targets it.
    stacked_commits: frozenset[str]
    # The pull requests whose head each commit is. A merge-queue head has none.
    pull_requests_by_commit: dict[str, tuple[int, ...]]


class _Pacer:
    """Waits `pause` seconds before every post but the first, so posts stay below GitHub's write limits."""

    def __init__(self, pause: float) -> None:
        self.pause = pause
        self.posts = 0

    def wait(self) -> None:
        if self.posts > 0:
            time.sleep(self.pause)
        self.posts += 1


def _add_repo_arguments(parser: CommandParser) -> None:
    parser.add_argument("--repo", type=str, required=True, help="Repository as owner/name.")
    parser.add_argument("--team-id", type=int, help="Team that registered the repository.")


class Command(BaseCommand):
    help = "Seed, repair, adopt renders, export and inspect a visual review repo's baseline ledger, and set its baseline mode"

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

        repair = subcommands.add_parser(
            "repair",
            help="Append entries until the ledger equals the baseline file at every position. Shadow mode only.",
        )
        _add_repo_arguments(repair)
        repair.add_argument("--run-type", type=str, required=True)
        repair.add_argument("--apply", action="store_true", help="Write the entries. Without it, only print the plan.")

        adopt_renders = subcommands.add_parser(
            "adopt-renders",
            help="Set the ledger to what a full default-branch run rendered, for the named identifiers. "
            "Ledger mode only.",
        )
        _add_repo_arguments(adopt_renders)
        adopt_renders.add_argument("--run-type", type=str, required=True)
        adopt_renders.add_argument("--run", type=UUID, required=True, dest="run_id", help="ID of the run to take from.")
        adopt_renders.add_argument(
            "--identifier",
            action="append",
            dest="identifiers",
            required=True,
            help="Snapshot identifier to adopt the render of. Repeat for more.",
        )
        adopt_renders.add_argument(
            "--apply", action="store_true", help="Write the entries. Without it, only print the plan."
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

        recheck = subcommands.add_parser(
            "recheck",
            help="Show the ledger verdict of every open pull request head and merge-queue head. --apply posts it.",
        )
        _add_repo_arguments(recheck)
        recheck.add_argument(
            "--run-type", action="append", dest="run_types", help="Check only this run type. Repeat for more."
        )
        recheck.add_argument(
            "--apply",
            action="store_true",
            help="Post the statuses. Needs the commit status gate, unless --only-success is given.",
        )
        recheck.add_argument(
            "--only-success",
            action="store_true",
            help="With --apply, post only the verdicts that are success. Works with the gate off, before the switch.",
        )
        recheck.add_argument(
            "--setup-check",
            default="",
            help="Name of the CI job that creates the run. A head without a run passes only when CI skipped it "
            "and the --report-check job succeeded. Needs exactly one --run-type. --apply needs it.",
        )
        recheck.add_argument(
            "--report-check",
            default="",
            help="Name of the CI job of this run type that reports a commit needs no run. A head without a run "
            "passes only when it succeeded. Needs exactly one --run-type. --apply needs it.",
        )
        recheck.add_argument(
            "--pause",
            type=float,
            default=8.0,
            help="Seconds to wait between two posts. The default stays below GitHub's 500 writes per hour.",
        )
        recheck.add_argument(
            "--pushed-within-days",
            type=int,
            default=7,
            help="Skip pull request heads committed longer ago than this. 0 covers every open pull request.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        repo = find_repo(options["repo"], options.get("team_id"))
        with team_scope(repo.team_id):
            match options["subcommand"]:
                case "seed":
                    self._seed(repo, options)
                case "repair":
                    self._repair(repo, options["run_type"], options["apply"])
                case "adopt-renders":
                    self._adopt_renders(repo, options)
                case "export":
                    self._export(repo, options["run_type"], options.get("output"))
                case "mode":
                    self._mode(repo, options.get("new_mode"))
                case "status-gate":
                    self._status_gate(repo, options.get("new_status_gate"))
                case "status":
                    self._status(repo)
                case "recheck":
                    self._recheck(repo, options)

    def _run_types(self, repo: Repo, named: list[str] | None) -> list[str]:
        configured = [run_type for run_type in (repo.baseline_file_paths or {}) if run_type != _DEFAULT_PATH_KEY]
        run_types = sorted(set(named or configured))
        if not run_types:
            raise CommandError(
                f"{repo.repo_full_name} names no run type in its baseline file paths. Name the run types with --run-type."
            )
        return run_types

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

        run_types = self._run_types(repo, options.get("run_types"))
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

    def _print_repair_plan(self, plan: contracts.BaselineLedgerRepair) -> None:
        self.stdout.write(f"{plan.run_type}: repair up to position {plan.cursor_position}, commit {plan.cursor_sha}")
        current_position: int | None = None
        for entry in plan.entries:
            if entry.position != current_position:
                current_position = entry.position
                pull_request = f"PR #{entry.pr_number}" if entry.pr_number is not None else "no PR"
                self.stdout.write(f"Position {entry.position}, commit {entry.commit_sha}, {pull_request}")
            new_hash = entry.content_hash or "removed"
            removal = " (removal)" if not entry.content_hash else ""
            self.stdout.write(f"  {entry.identifier}: {entry.previous_hash or 'absent'} -> {new_hash}{removal}")
        positions = {entry.position for entry in plan.entries}
        identifiers = {entry.identifier for entry in plan.entries}
        self.stdout.write(
            f"{len(plan.entries)} entries at {len(positions)} positions for {len(identifiers)} identifiers"
        )
        self.stdout.write(
            f"Drift at the cursor: {len(plan.drift_before)} identifiers before, {len(plan.drift_after)} after"
        )
        for identifier in plan.drift_before:
            self.stdout.write(f"  Drifted before: {identifier}")
        for identifier in plan.drift_after:
            self.stdout.write(f"  Still drifted: {identifier}")
        for mismatch in plan.mismatches:
            self.stdout.write(f"Differs from the file at its commit: {mismatch}")

    def _print_repair_progress(self, read: int, total: int) -> None:
        self.stdout.write(f"Read the baseline file at {read} of {total} positions")

    def _repair(self, repo: Repo, run_type: str, apply: bool) -> None:
        try:
            plan = api.repair_baseline_ledger(
                repo.id, repo.team_id, run_type, apply=apply, on_progress=self._print_repair_progress
            )
        except (api.BaselineRepairError, api.GitHubCommitError) as e:
            raise CommandError(str(e)) from e
        self._print_repair_plan(plan)
        if apply:
            self.stdout.write(f"Wrote {len(plan.entries)} entries.")
            return
        self.stdout.write("Dry run, nothing written. Pass --apply to write.")

    def _print_adoption_plan(self, plan: contracts.BaselineLedgerAdoption) -> None:
        self.stdout.write(
            f"{plan.run_type}: adopt renders at position {plan.cursor_position}, commit {plan.cursor_sha}, "
            f"from run {plan.run_id} at position {plan.run_position}"
        )
        rows = [("Identifier", "Ledger", "Render", "Action", "Open approvals")]
        for item in plan.items:
            action = "already matches" if item.already_matches else "append"
            rows.append(
                (item.identifier, item.ledger_hash or "absent", item.render_hash, action, str(item.open_approvals))
            )
        widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
        for row in rows:
            self.stdout.write("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())

    def _adopt_renders(self, repo: Repo, options: dict[str, Any]) -> None:
        apply = options["apply"]
        try:
            adopt = api.adopt_ledger_renders if apply else api.plan_ledger_adoption
            plan = adopt(repo.id, repo.team_id, options["run_type"], options["run_id"], options["identifiers"])
        except api.BaselineAdoptionError as e:
            raise CommandError(str(e)) from e
        self._print_adoption_plan(plan)
        if apply:
            self.stdout.write(f"Wrote {len(plan.to_append)} entries.")
            return
        self.stdout.write("Dry run, nothing was written. Pass --apply to write.")

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

        self._write_pull_requests_gated_by_status(repo)

    def _write_pull_requests_gated_by_status(self, repo: Repo) -> None:
        # These runs passed their CI job on the commit status alone, so removing the required statuses
        # from the ruleset leaves their pull requests without a gate until a new run replaces them. A run
        # without unreviewed or unfinalized changes has nothing for the gate to hold back.
        awaiting_finalize = RunSnapshot.objects.using(WRITER_DB).filter(
            run_id=OuterRef("id"),
            review_state=ReviewState.APPROVED,
            result__in=(SnapshotResult.NEW, SnapshotResult.CHANGED),
        )
        unreviewed = (
            RunSnapshot.objects.using(WRITER_DB)
            .filter(run_id=OuterRef("id"))
            .exclude(result=SnapshotResult.UNCHANGED)
            .exclude(is_quarantined=True)
            .exclude(review_state__in=(ReviewState.TOLERATED, ReviewState.APPROVED))
        )
        pr_numbers = list(
            Run.objects.using(WRITER_DB)
            .alias(unreviewed=Exists(unreviewed), awaiting_finalize=Exists(awaiting_finalize))
            .filter(
                Q(status__in=(RunStatus.PENDING, RunStatus.PROCESSING))
                | Q(status=RunStatus.COMPLETED, unreviewed=True)
                | Q(status=RunStatus.COMPLETED, awaiting_finalize=True),
                repo_id=repo.id,
                gate=RunGate.COMMIT_STATUS,
                purpose=RunPurpose.REVIEW,
                approved=False,
                superseded_by__isnull=True,
                pr_number__isnull=False,
            )
            .order_by("pr_number")
            .values_list("pr_number", flat=True)
            .distinct()
        )
        if not pr_numbers:
            return
        shown = ", ".join(f"#{pr_number}" for pr_number in pr_numbers[:_MAX_LISTED_PULL_REQUESTS])
        rest = len(pr_numbers) - _MAX_LISTED_PULL_REQUESTS
        more = f", and {rest} more" if rest > 0 else ""
        self.stdout.write(f"Pull requests whose run is gated by the commit status: {shown}{more}")

    def _pushed_within(self, repo: Repo, heads: list[github_api.BranchHead], days: int) -> list[github_api.BranchHead]:
        if days == 0:
            return heads
        cutoff = timezone.now() - timedelta(days=days)
        kept: list[github_api.BranchHead] = []
        for head in heads:
            try:
                committed_at = github_api.commit_committer_date(repo, head.commit_sha)
            except github_api.GITHUB_READ_REFUSED as e:
                raise CommandError(
                    f"GitHub refused the commit read of {head.commit_sha}. Nothing was posted. Run recheck again later."
                ) from e
            if committed_at is None or committed_at >= cutoff:
                kept.append(head)
        return kept

    def _heads(self, repo: Repo, pushed_within_days: int) -> _Heads:
        default_branch = github_api.default_branch_name(repo)
        if default_branch is None:
            raise CommandError("GitHub did not name the default branch. Nothing was posted.")
        # A stacked pull request gets its status now too. When its parent merges, it is retargeted
        # to the default branch, and no workflow runs on that change to post the status.
        pull_requests = github_api.open_pull_request_heads(repo)
        merge_queue = github_api.merge_queue_branch_heads(repo)
        if pull_requests is None or merge_queue is None:
            raise CommandError(
                "GitHub did not list the open pull requests or the merge-queue branches. Nothing was posted."
            )
        # CI skips the setup job on a fork, whose workflow gets no secrets, so a skipped job proves nothing
        # there. A fork pull request is recreated in the repository before it merges, so it gets no status.
        in_repo = [head for head in pull_requests if not head.from_fork]
        forks = len(pull_requests) - len(in_repo)
        # Each post counts against GitHub's write limit, so the pass leaves out heads that get their status
        # another way. CI runs on `ready_for_review`, which posts a draft's status. An old head without a
        # status cannot merge, as with a status that is not green, and its next push or CI re-run posts it.
        ready = [head for head in in_repo if not head.draft]
        drafts = len(in_repo) - len(ready)
        kept = self._pushed_within(repo, ready, pushed_within_days)
        on_default_branch = sum(1 for head in kept if head.base_ref == default_branch)
        self.stdout.write(
            f"{len(kept)} open pull requests ({on_default_branch} on the default branch, "
            f"{len(kept) - on_default_branch} on other branches), {len(merge_queue)} merge-queue branches, "
            f"{forks} fork pull requests skipped, {drafts} drafts skipped, "
            f"{len(ready) - len(kept)} not pushed within {pushed_within_days} days skipped."
        )
        on_default = {head.commit_sha for head in kept if head.base_ref == default_branch}
        stacked = {head.commit_sha for head in kept if head.base_ref != default_branch}
        pull_requests_by_commit: dict[str, tuple[int, ...]] = {}
        for head in kept:
            pull_requests_by_commit[head.commit_sha] = (
                *pull_requests_by_commit.get(head.commit_sha, ()),
                head.pr_number,
            )
        return _Heads(
            heads=kept + merge_queue,
            stacked_commits=frozenset(stacked - on_default),
            pull_requests_by_commit=pull_requests_by_commit,
        )

    def _show_verdicts(
        self, repo: Repo, heads: _Heads, run_types: list[str], setup_check: str, report_check: str
    ) -> None:
        pull_requests_by_reason: dict[tuple[str, str, str], set[int]] = {}
        for head in heads.heads:
            stacked = head.commit_sha in heads.stacked_commits
            for run_type in run_types:
                try:
                    verdict = commit_status.ledger_verdict(
                        repo,
                        head.commit_sha,
                        run_type,
                        setup_check,
                        report_check,
                        stacked=stacked,
                        pr_numbers=heads.pull_requests_by_commit.get(head.commit_sha, ()),
                    )
                except github_api.GITHUB_READ_REFUSED:
                    verdict = commit_status.StatusVerdict(state="unknown", description="read refused")
                # Counts and the partial-run note would give almost every head a line of its own.
                reason = _COUNT_RE.sub("N", verdict.description.removesuffix(" (partial run)"))
                pull_requests_by_reason.setdefault((run_type, verdict.state, reason), set()).add(head.pr_number)

        self.stdout.write("Dry run, nothing was posted. Pull requests per run type, state and reason:")
        for (run_type, state, reason), pr_numbers in sorted(pull_requests_by_reason.items()):
            listed = sorted(pr_numbers)
            shown = ", ".join(f"#{pr_number}" for pr_number in listed[:_MAX_LISTED_PULL_REQUESTS])
            rest = len(listed) - _MAX_LISTED_PULL_REQUESTS
            more = f", and {rest} more" if rest > 0 else ""
            self.stdout.write(f"{run_type} {state} ({len(listed)}) {reason}: {shown}{more}")

    def _counts(self, outcomes: Counter[commit_status.RecheckPost], legacy_replaced: int) -> str:
        return (
            f"{outcomes[commit_status.RecheckPost.POSTED]} posted, "
            f"{outcomes[commit_status.RecheckPost.UNCHANGED]} skipped as already posted, "
            f"{outcomes[commit_status.RecheckPost.NOT_SUCCESS]} skipped as not success, "
            f"{outcomes[commit_status.RecheckPost.STACKED_WITHOUT_RUN]} skipped as stacked without a run, "
            f"{outcomes[commit_status.RecheckPost.RETARGETED_WITHOUT_RUN]} skipped as retargeted without a run, "
            f"{legacy_replaced} old statuses replaced"
        )

    def _post_verdicts(
        self,
        repo: Repo,
        heads: _Heads,
        run_types: list[str],
        setup_check: str,
        report_check: str,
        options: dict[str, Any],
    ) -> None:
        only_success = options["only_success"]
        pacer = _Pacer(options["pause"])
        commits = sorted({head.commit_sha for head in heads.heads})
        statuses = [(commit_sha, run_type) for commit_sha in commits for run_type in run_types]
        outcomes: Counter[commit_status.RecheckPost] = Counter()
        legacy_replaced = 0
        for index, (commit_sha, run_type) in enumerate(statuses):
            # A refusal is usually GitHub's rate limit, and every further request would be refused too.
            stopped = CommandError(
                f"GitHub refused a read or a post for the {run_type} status of {commit_sha}, so the command "
                f"stopped. {self._counts(outcomes, legacy_replaced)}, {len(statuses) - index} remain. "
                "Run recheck --apply again: it skips what a head already carries."
            )
            try:
                current = github_api.commit_statuses(repo, commit_sha, Priority.BATCH)
            except github_api.GITHUB_READ_REFUSED:
                current = None
            if current is None:
                raise stopped
            result = commit_status.publish_recheck(
                repo,
                commit_sha,
                run_type,
                setup_check,
                report_check,
                current=current,
                only_success=only_success,
                wait=pacer.wait,
                stacked=commit_sha in heads.stacked_commits,
                pr_numbers=heads.pull_requests_by_commit.get(commit_sha, ()),
            )
            if result.outcome == commit_status.RecheckPost.STOPPED:
                raise stopped
            outcomes[result.outcome] += 1
            if only_success:
                continue
            legacy = commit_status.replace_legacy_status(
                repo, commit_sha, run_type, gate_state=result.state, current=current, wait=pacer.wait
            )
            if legacy == commit_status.RecheckPost.STOPPED:
                raise stopped
            legacy_replaced += legacy == commit_status.RecheckPost.POSTED
        self.stdout.write(f"{self._counts(outcomes, legacy_replaced)} on {len(commits)} commits.")

    def _recheck(self, repo: Repo, options: dict[str, Any]) -> None:
        apply = options["apply"]
        # With the gate on, publishers post failures at any time, and a success posted from a verdict
        # read before the pacing sleep could overwrite one.
        if options["only_success"] and repo.commit_status_gate_enabled:
            raise CommandError(
                "--only-success is for before the sitting, with the commit status gate off. "
                "With the gate on, run --apply without it. Nothing was posted."
            )
        if apply and not options["only_success"] and not repo.commit_status_gate_enabled:
            raise CommandError(
                "--apply posts the gate's status, so it needs the commit status gate. "
                "Without --apply the command only shows the statuses, and --only-success posts only the greens."
            )
        setup_check = options["setup_check"]
        report_check = options["report_check"]
        # Without it every head without a run would get a pending status.
        if apply and not setup_check:
            raise CommandError(
                "--apply needs --setup-check, the CI job that creates the run, to tell a head that needs no run "
                "from one whose run is gone. Nothing was posted."
            )
        if apply and not report_check:
            raise CommandError(
                "--apply needs --report-check, the CI job that reports a commit needs no run. Nothing was posted."
            )
        run_types = self._run_types(repo, options.get("run_types"))
        # Each run type has its own CI job that creates its run.
        if (setup_check or report_check) and len(run_types) != 1:
            raise CommandError(
                "--setup-check and --report-check name the jobs of one run type. Pass exactly one --run-type with them."
            )
        heads = self._heads(repo, options["pushed_within_days"])
        if apply:
            self._post_verdicts(repo, heads, run_types, setup_check, report_check, options)
        else:
            self._show_verdicts(repo, heads, run_types, setup_check, report_check)
