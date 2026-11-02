"""Local dev seeding: a spread of realistic Inbox reports, their task runs, and a demo chat.

Each report goes through the same `_persist_agentic_report_artefacts` path the agentic flow uses
(priority / actionability / reviewers / findings artefacts), then advances to a terminal state.

Report task runs get a synthetic JSONL transcript in object storage, so the inbox's inline run viewer
renders a real-looking agent log without running a sandbox. Tasks/runs are created through the tasks
facade (the product is isolated), never by touching its ORM.

Callers own the DEBUG / not-cloud guard: `seed_inbox_data` and the Hedgebox demo matrix.
"""

import json
from collections.abc import Callable
from pathlib import Path

from django.conf import settings
from django.db import transaction

from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.artefact_schemas import (
    Commit,
    NoteArtefact,
    RelevantCommit,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportRefund
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.signals.backend.temporal.agentic.report import _persist_agentic_report_artefacts
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.repo_selection_types import ReportResearchContext

_FIXTURES_DIR = Path(__file__).resolve().parent / "report_generation" / "fixtures"
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

_REVIEWER_COMMIT_REASONS = [
    "Changed the backend path involved in this report.",
    "Recently updated the affected UI component.",
    "Built the API behavior used by this report.",
    "Changed tests around the affected behavior.",
    "Recently worked in the owning product area.",
    "Updated the related task workflow.",
    "Changed the nearest shared dependency.",
    "Maintains the code path where this issue occurs.",
]


class NoSeedFixturesError(Exception):
    pass


@frozen
class _SeedFixture:
    name: str
    repository: str
    result: ReportResearchOutput


@frozen
class SeededInbox:
    report_ids: tuple[str, ...]
    task_ids: tuple[str, ...]


@frozen
class SeededChat:
    task_id: str
    run_id: str


def _ignore(_message: str) -> None:
    return None


def seed_demo_inbox(
    *,
    team_id: int,
    user_id: int,
    count: int | None = None,
    with_runs: bool = True,
    github_optional: bool = False,
    clear: bool = False,
    log: Callable[[str], None] | None = None,
) -> SeededInbox:
    """Seed `count` reports (default: one per fixture) that name `user_id` as their first reviewer.

    `github_optional` seeds the shape GitHub-optional research leaves without a GitHub integration:
    a `data_only` repo selection with no repository, commits, GitHub reviewers, or runs.
    """
    write = log or _ignore
    team = Team.objects.select_related("organization").get(id=team_id)
    user_uuid = str(User.objects.values_list("uuid", flat=True).get(id=user_id))
    fixtures = _load_fixtures(write)
    if clear:
        _clear_existing(team, write)

    report_ids: list[str] = []
    task_ids: list[str] = []
    for index in range(count or len(fixtures)):
        fixture = fixtures[index % len(fixtures)]
        result = fixture.result
        repository = None if github_optional else fixture.repository
        final_status = _FINAL_STATES[index % len(_FINAL_STATES)]
        report = _seed_report(team, result, repository, final_status, write)
        write(f"  · {report.status:<13} {result.title[:70]} ({fixture.name})")

        _add_extra_log_artefacts(team.id, str(report.id), repository, index)
        _add_suggested_reviewers(team.id, str(report.id), repository, index, user_uuid)
        report_ids.append(str(report.id))
        if with_runs and repository is not None:
            task_id = _seed_task_run(team, user_id, report, repository, index, write)
            if task_id is not None:
                task_ids.append(task_id)

    return SeededInbox(report_ids=tuple(report_ids), task_ids=tuple(task_ids))


def seed_demo_chat(*, team_id: int, user_id: int) -> SeededChat:
    """Create one completed, user-created chat with a short user/agent transcript."""
    if not settings.OBJECT_STORAGE_ENABLED:
        raise RuntimeError("Demo chat requires object storage. Enable OBJECT_STORAGE_ENABLED before seeding a chat.")
    team = Team.objects.get(id=team_id)
    # The transcript lives in object storage, which is optional locally. Roll the task back when the
    # write fails, so the user never gets a chat that opens to an empty log.
    with transaction.atomic():
        created = tasks_facade.create_and_run_task(
            team=team,
            title="Check the demo signup flow",
            description="Which steps of the Hedgebox signup flow are worth checking first?",
            origin_product=tasks_facade.TaskOriginProduct.USER_CREATED,
            user_id=user_id,
            repository=None,
            create_pr=False,
            start_workflow=False,
        )
        run = created.latest_run
        if run is None:
            raise RuntimeError("create_and_run_task returned a task without a run")
        task_id, run_id = str(created.task_id), str(run.id)
        entries = [
            _user_message("Which steps of the demo signup flow should I check first?"),
            _agent_message(
                "Start with the step where most people drop off. Open the signup funnel, compare it week "
                "over week, and then watch two or three recordings of people who left at that step."
            ),
            _end_turn(),
        ]
        tasks_facade.append_task_run_log(run_id, task_id, team.id, entries=entries)
        persisted = tasks_facade.read_task_run_logs(run_id, task_id, team.id)
        if not persisted or [json.loads(line) for line in persisted.splitlines() if line.strip()] != entries:
            raise RuntimeError("Demo chat transcript was not saved. Check object storage before seeding a chat.")
        tasks_facade.update_task_run(run_id, task_id, team.id, validated_data={"status": "completed"})
    return SeededChat(task_id=task_id, run_id=run_id)


# ── setup ──────────────────────────────────────────────────────────────────


def _load_fixtures(write: Callable[[str], None]) -> list[_SeedFixture]:
    fixtures: list[_SeedFixture] = []
    for path in sorted(_FIXTURES_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            write(f"Skipping unparseable fixture {path.name}: {e}")
            continue
        if not isinstance(payload, dict):
            continue
        result_payload = payload.get("result")
        if result_payload is None:
            continue
        try:
            result = ReportResearchOutput.model_validate(result_payload)
        except Exception as e:
            write(f"Skipping invalid fixture {path.name}: {e}")
            continue
        repository = payload.get("repository") or _DEFAULT_REPOSITORY
        fixtures.append(_SeedFixture(name=path.stem, repository=repository, result=result))
    if not fixtures:
        raise NoSeedFixturesError(f"No usable report fixtures found in {_FIXTURES_DIR}")
    return fixtures


def _clear_existing(team: Team, write: Callable[[str], None]) -> None:
    # Refunds RESTRICT report deletion; reseeding means a full reset.
    SignalReportRefund.objects.for_team(team.id).delete()
    deleted, _ = SignalReport.objects.filter(team=team).delete()
    write(f"Deleted {deleted} existing signal report row(s) for team {team.id}")


# ── report + artefacts ─────────────────────────────────────────────────────


def _seed_report(
    team: Team,
    result: ReportResearchOutput,
    repository: str | None,
    final_status: SignalReport.Status,
    write: Callable[[str], None],
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

    if repository is None:
        repo_selection = RepoSelectionResult(
            repository=None,
            reason="Research will use project data without code access.",
            research_context=ReportResearchContext(mode="data_only", repository_status="no_integration"),
            autostart_eligible=False,
        )
    else:
        repo_selection = RepoSelectionResult(repository=repository, reason="seed_inbox_data: synthetic seed report")
    async_to_sync(_persist_agentic_report_artefacts)(team.id, str(report.id), result, repo_selection)

    _advance_to_final(report, result, final_status, write)
    return report


def _advance_to_final(
    report: SignalReport,
    result: ReportResearchOutput,
    final_status: SignalReport.Status,
    write: Callable[[str], None],
) -> None:
    with transaction.atomic():
        report.refresh_from_db()
        report.save(
            update_fields=report.transition_to(SignalReport.Status.READY, title=result.title, summary=result.summary)
        )
        if final_status == SignalReport.Status.READY:
            return
        try:
            report.save(update_fields=report.transition_to(final_status))
        except Exception as e:
            # Keep the report at READY rather than aborting the seed on an unexpected transition.
            write(f"    left at READY ({final_status} transition failed: {e})")


def _add_extra_log_artefacts(team_id: int, report_id: str, repository: str | None, index: int) -> None:
    SignalReportArtefact.add_log(
        team_id=team_id,
        report_id=report_id,
        content=NoteArtefact(note="Seeded by `seed_inbox_data` for local UI development.", author="seed_inbox_data"),
        attribution=ArtefactAttribution.system(),
    )
    if repository is None:
        return
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


def _add_suggested_reviewers(team_id: int, report_id: str, repository: str | None, index: int, user_uuid: str) -> None:
    # Reviewers are normally derived from finding commit hashes via GitHub, which won't resolve
    # locally — so seed them directly. Counts vary (1..7) so some reports exercise the list-overflow.
    # Without a repository there are no commits to derive GitHub reviewers from.
    reviewer_count = 0 if repository is None else 1 + (index % 7)
    logins = ["timgl", "marius", "yakkomajuri", "neilkakkar", "macobo", "hazzadous", "pauldambra", "benjackwhite"]
    entries = [
        SuggestedReviewerEntry(
            github_login=logins[i % len(logins)],
            github_name=logins[i % len(logins)].title(),
            relevant_commits=[
                RelevantCommit(
                    reason=_REVIEWER_COMMIT_REASONS[(index + i) % len(_REVIEWER_COMMIT_REASONS)],
                    sha=f"{(index + i + 1) * 2468013:07x}",
                    url=f"https://github.com/{repository}/commit/{(index + i + 1) * 2468013:07x}",
                )
            ],
            # Alternate so both the reason and no-reason render paths get exercised locally.
            reason="Top recent author on the affected surface." if i % 2 == 0 else None,
        )
        for i in range(reviewer_count)
    ]
    # The seeding user leads the list, so the reports reach their Today home, which shows only reports naming them.
    entries.insert(0, SuggestedReviewerEntry(user_uuid=user_uuid, reason="Owns the affected surface."))
    SignalReportArtefact.append_status(
        team_id=team_id,
        report_id=report_id,
        content=SuggestedReviewers(entries),
        attribution=ArtefactAttribution.system(),
        reevaluate_autostart=False,
    )


# ── task run + logs ────────────────────────────────────────────────────────


def _seed_task_run(
    team: Team, user_id: int, report: SignalReport, repository: str, index: int, write: Callable[[str], None]
) -> str | None:
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
        write(f"    skipped task run (task creation failed: {e})")
        return None

    run = created.latest_run
    if run is None:
        write("    skipped task run (no run was created)")
        return None

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
    # Production dual-write (`SignalReportTask` bridge row + `task_run` artefact) so seeded
    # reports are billable-faithful — the billing query is rooted on the bridge, and an
    # artefact alone makes the PR visible in the UI but not chargeable/refundable.
    record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=task_id, run_id=run_id)
    return task_id


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
