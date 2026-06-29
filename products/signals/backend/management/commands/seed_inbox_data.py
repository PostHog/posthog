"""Local dev tool: seed the Signals inbox with a spread of realistic reports + task runs.

Drops several fully-formed `SignalReport`s into the inbox so the UI has something to look at —
each one persisted through the same `_persist_agentic_report_artefacts` path the agentic flow uses
(priority / actionability / reviewers / findings artefacts), then advanced to a terminal state.

Most reports also get a `tasks.Task` + `TaskRun` with a synthetic JSONL transcript written to object
storage, so the inbox's inline run viewer renders a real-looking agent log without running a sandbox.
Tasks/runs are created through the tasks facade (the product is isolated) — never by touching its ORM.

DEBUG only.

    python manage.py seed_inbox_data --team-id 1
    python manage.py seed_inbox_data --team-id 1 --count 12 --clear
    python manage.py seed_inbox_data --team-id 1 --no-runs
"""

import json
import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models import OrganizationMembership, Team

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    Commit,
    NoteArtefact,
    RelevantCommit,
    SuggestedReviewerEntry,
    SuggestedReviewers,
    TaskRunArtefact,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import _persist_agentic_report_artefacts
from products.tasks.backend.facade import api as tasks_facade

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "report_generation" / "fixtures"
_DEFAULT_REPOSITORY = "posthog/posthog"

# Terminal states cycled across the seeded reports so the inbox shows more than one status. Kept to
# states reachable from in_progress without extra side effects; READY dominates since it's the
# actionable inbox state users actually triage.
_FINAL_STATES = [
    SignalReport.Status.READY,
    SignalReport.Status.READY,
    SignalReport.Status.PENDING_INPUT,
    SignalReport.Status.READY,
    SignalReport.Status.RESOLVED,
]


class Command(BaseCommand):
    help = "Seed the Signals inbox with realistic reports and task runs (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed reports for")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="User to attribute tasks to (default: first member of the team's organization)",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=None,
            help="How many reports to create (default: one per fixture; cycles fixtures when larger)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete the team's existing signal reports (and their artefacts) before seeding",
        )
        parser.add_argument(
            "--no-runs",
            dest="with_runs",
            action="store_false",
            help="Skip creating task runs + logs (reports and artefacts only)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        team = self._get_team(options["team_id"])
        user_id = self._resolve_user_id(team, options["user_id"])
        fixtures = self._load_fixtures()
        count = options["count"] or len(fixtures)

        if options["clear"]:
            self._clear_existing(team)

        created = 0
        for index in range(count):
            name, repository, result = fixtures[index % len(fixtures)]
            final_status = _FINAL_STATES[index % len(_FINAL_STATES)]
            report = self._seed_report(team, result, repository, final_status)
            self.stdout.write(f"  · {report.status:<13} {result.title[:70]} ({name})")

            self._add_extra_log_artefacts(team.id, str(report.id), repository, index)
            self._add_suggested_reviewers(team.id, str(report.id), repository, index)
            if options["with_runs"]:
                self._seed_task_run(team, user_id, report, repository, index)
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded {created} report(s) for team {team.id} ({team.name})."))

    # ── setup ──────────────────────────────────────────────────────────────────

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.select_related("organization").get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

    def _resolve_user_id(self, team: Team, user_id: int | None) -> int:
        if user_id is not None:
            return user_id
        membership = (
            OrganizationMembership.objects.filter(organization_id=team.organization_id)
            .order_by("joined_at")
            .values_list("user_id", flat=True)
            .first()
        )
        if membership is None:
            raise CommandError(f"Team {team.id}'s organization has no members; pass --user-id explicitly")
        return membership

    def _load_fixtures(self) -> list[tuple[str, str, ReportResearchOutput]]:
        fixtures: list[tuple[str, str, ReportResearchOutput]] = []
        for path in sorted(_FIXTURES_DIR.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                self.stdout.write(self.style.WARNING(f"Skipping unparseable fixture {path.name}: {e}"))
                continue
            if not isinstance(payload, dict):
                continue
            result_payload = payload.get("result")
            if result_payload is None:
                continue
            try:
                result = ReportResearchOutput.model_validate(result_payload)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skipping invalid fixture {path.name}: {e}"))
                continue
            repository = payload.get("repository") or _DEFAULT_REPOSITORY
            fixtures.append((path.stem, repository, result))
        if not fixtures:
            raise CommandError(f"No usable report fixtures found in {_FIXTURES_DIR}")
        return fixtures

    def _clear_existing(self, team: Team) -> None:
        deleted, _ = SignalReport.objects.filter(team=team).delete()
        self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing signal report row(s) for team {team.id}"))

    # ── report + artefacts ─────────────────────────────────────────────────────

    def _seed_report(
        self, team: Team, result: ReportResearchOutput, repository: str, final_status: SignalReport.Status
    ) -> SignalReport:
        signal_count = max(len(result.effective_findings()), 1)

        with transaction.atomic():
            report = SignalReport.objects.create(
                team=team,
                status=SignalReport.Status.POTENTIAL,
                signal_count=signal_count,
                total_weight=float(signal_count),
            )
            report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
            report.save(update_fields=report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3))

        # The persist path only writes `new_artefacts`; fixtures captured mid-run keep content in
        # `old_artefacts`, so coalesce everything into `new_artefacts` to guarantee the judgments /
        # findings actually land for a seeded report.
        result = result.model_copy(
            update={"new_artefacts": [*result.old_artefacts, *result.new_artefacts], "old_artefacts": []}
        )

        repo_selection = RepoSelectionResult(repository=repository, reason="seed_inbox_data: synthetic seed report")
        asyncio.run(_persist_agentic_report_artefacts(team.id, str(report.id), result, repo_selection))

        self._advance_to_final(report, result, final_status)
        return report

    def _advance_to_final(
        self, report: SignalReport, result: ReportResearchOutput, final_status: SignalReport.Status
    ) -> None:
        with transaction.atomic():
            report.refresh_from_db()
            report.save(
                update_fields=report.transition_to(
                    SignalReport.Status.READY, title=result.title, summary=result.summary
                )
            )
            if final_status == SignalReport.Status.READY:
                return
            try:
                report.save(update_fields=report.transition_to(final_status))
            except Exception as e:
                # Keep the report at READY rather than aborting the seed on an unexpected transition.
                self.stdout.write(self.style.WARNING(f"    left at READY ({final_status} transition failed: {e})"))

    def _add_extra_log_artefacts(self, team_id: int, report_id: str, repository: str, index: int) -> None:
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=NoteArtefact(
                note="Seeded by `seed_inbox_data` for local UI development.", author="seed_inbox_data"
            ),
            attribution=ArtefactAttribution.system(),
        )
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=report_id,
            content=Commit(
                repository=repository,
                branch=f"signals/seed-fix-{index + 1}",
                commit_sha=f"{(index + 1) * 1111111:07x}",
                message="fix: address the issue surfaced by this report",
                note="Synthetic commit from the inbox seed script.",
            ),
            attribution=ArtefactAttribution.system(),
        )

    def _add_suggested_reviewers(self, team_id: int, report_id: str, repository: str, index: int) -> None:
        # Reviewers are normally derived from finding commit hashes via GitHub, which won't resolve
        # locally — so seed them directly. Counts vary (1..7) so some reports exercise the list-overflow.
        reviewer_count = 1 + (index % 7)
        logins = ["timgl", "marius", "yakkomajuri", "neilkakkar", "macobo", "hazzadous", "pauldambra", "benjackwhite"]
        entries = [
            SuggestedReviewerEntry(
                github_login=logins[i % len(logins)],
                github_name=logins[i % len(logins)].title(),
                relevant_commits=[
                    RelevantCommit(
                        reason="Authored the most relevant code path for this report.",
                        sha=f"{(index + i + 1) * 2468013:07x}",
                        url=f"https://github.com/{repository}/commit/{(index + i + 1) * 2468013:07x}",
                    )
                ],
            )
            for i in range(reviewer_count)
        ]
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            content=SuggestedReviewers(entries),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )

    # ── task run + logs ────────────────────────────────────────────────────────

    def _seed_task_run(self, team: Team, user_id: int, report: SignalReport, repository: str, index: int) -> None:
        try:
            created = tasks_facade.create_and_run_task(
                team=team,
                title=report.title or "Investigate inbox report",
                description=report.summary or "Synthetic implementation task seeded for the inbox.",
                origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
                user_id=user_id,
                repository=repository,
                create_pr=False,
                start_workflow=False,
                signal_report_id=str(report.id),
                internal=False,
            )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    skipped task run (task creation failed: {e})"))
            return

        run = created.latest_run
        if run is None:
            self.stdout.write(self.style.WARNING("    skipped task run (no run was created)"))
            return

        task_id, run_id = str(created.task_id), str(run.id)
        branch = f"signals/seed-fix-{index + 1}"
        pr_url = f"https://github.com/{repository}/pull/{1000 + index}"

        tasks_facade.append_task_run_log(
            run_id, task_id, team.id, entries=_build_transcript(report.title or "this report", index)
        )
        tasks_facade.update_task_run(
            run_id,
            task_id,
            team.id,
            validated_data={
                "status": "completed",
                "stage": "build",
                "branch": branch,
                "output": {"pr_url": pr_url, "branch": branch},
            },
        )
        SignalReportArtefact.add_log(
            team_id=team.id,
            report_id=str(report.id),
            content=TaskRunArtefact(
                task_id=task_id, run_id=run_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
            ),
            attribution=ArtefactAttribution.from_task(task_id),
        )


# ── synthetic transcript ───────────────────────────────────────────────────────


def _agent_message(text: str) -> dict:
    return {
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}}},
        }
    }


def _user_message(text: str) -> dict:
    return {
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "user_message", "content": {"type": "text", "text": text}}},
        }
    }


def _tool_call(title: str) -> dict:
    return {
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "tool_call", "title": title}},
        }
    }


def _usage_update(used: int, cost: float) -> dict:
    return {
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "usage_update", "used": used, "cost": cost}},
        }
    }


def _end_turn() -> dict:
    return {"notification": {"result": {"stopReason": "end_turn"}}}


def _build_transcript(report_title: str, index: int) -> list[dict]:
    """A short, realistic agent transcript in the JSONL shape the sandbox viewer parses."""
    tool_titles = ["grep", "read_file", "git blame", "edit_file", "run_tests"]
    return [
        _user_message(f"Investigate and fix: {report_title}"),
        _agent_message("Reading the report and locating the relevant code paths."),
        _tool_call(tool_titles[index % len(tool_titles)]),
        _agent_message("Found the root cause. The issue is a missing guard around the affected branch."),
        _tool_call("edit_file"),
        _agent_message("Applied the fix and added a regression test."),
        _tool_call("run_tests"),
        _usage_update(used=1850 + index * 120, cost=0.0021 + index * 0.0003),
        _agent_message("Tests pass. Opening a pull request with the change."),
        _end_turn(),
    ]
