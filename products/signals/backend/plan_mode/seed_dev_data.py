"""Dev-only seeding for the Plan tab UI. Run via:

    DJANGO_SETTINGS_MODULE=posthog.settings python -m products.signals.backend.plan_mode.seed_dev_data

Creates plan reports with realistic artefacts in Postgres, including the planning `task_run` marker
artefact that drives Plan tab membership (plans have no backing signal). Idempotent-ish: reports are
keyed by title, so re-running skips ones that already exist.
"""

from datetime import UTC, datetime, timedelta

import django

django.setup()


from posthog.models import Team, User  # noqa: E402

from products.signals.backend.artefact_schemas import (  # noqa: E402
    ActionabilityAssessment,
    ActionabilityChoice,
    CodeReference,
    NoteArtefact,
    Priority,
    PriorityAssessment,
    QuestionArtefact,
    SafetyJudgment,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact  # noqa: E402
from products.signals.backend.task_run_artefacts import append_task_run_artefact  # noqa: E402
from products.tasks.backend.models import Task  # noqa: E402

TEAM_ID = 1


def _seed_plan(
    *,
    team: Team,
    user: User,
    title: str,
    summary: str,
    notes: list[str],
    code_refs: list[CodeReference],
    created_ago: timedelta,
    questions: list[QuestionArtefact] | None = None,
    feedback: list[QuestionArtefact] | None = None,
) -> str | None:
    if SignalReport.objects.filter(team=team, title=title).exists():
        print(f"skip (exists): {title}")  # noqa: T201
        return None

    attribution = ArtefactAttribution.from_user(user.id)
    now = datetime.now(UTC)

    report = SignalReport.objects.create(
        team=team,
        status=SignalReport.Status.READY,
        title=title,
        summary=summary,
        signal_count=1,
        total_weight=1.0,
    )
    # Backdate so the list ordering (newest report first) has variety.
    SignalReport.objects.filter(id=report.id).update(created_at=now - created_ago, updated_at=now - created_ago)
    report_id = str(report.id)

    common = {"team_id": team.id, "report_id": report_id, "attribution": attribution}
    # reevaluate_autostart=False: seeded reviewers on a P1 immediately-actionable report must not
    # trip the real auto-start machinery.
    SignalReportArtefact.append(
        content=PriorityAssessment(explanation="User-driven plan: always P1.", priority=Priority.P1),
        reevaluate_autostart=False,
        **common,
    )
    SignalReportArtefact.append(
        content=ActionabilityAssessment(
            explanation="User-driven plan: actionable by definition.",
            actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
            already_addressed=False,
        ),
        reevaluate_autostart=False,
        **common,
    )
    SignalReportArtefact.append(
        content=SafetyJudgment(choice=True, explanation=None), reevaluate_autostart=False, **common
    )
    SignalReportArtefact.append(
        content=SuggestedReviewers(
            [SuggestedReviewerEntry(github_login="oliver-posthog", github_name="Oliver Browne", relevant_commits=[])]
        ),
        reevaluate_autostart=False,
        **common,
    )
    for note in notes:
        SignalReportArtefact.add_log(
            content=NoteArtefact(note=note, author="planning agent"),
            team_id=team.id,
            report_id=report_id,
            attribution=attribution,
        )
    for ref in code_refs:
        SignalReportArtefact.add_log(content=ref, team_id=team.id, report_id=report_id, attribution=attribution)

    # The planning task_run artefact is the Plan tab membership marker (see plan_mode/queries.py).
    task = Task.objects.create(
        team=team,
        title="Plan a new project",
        description="seeded planning conversation",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        created_by=user,
    )
    # Task-attributed: questions FROM agents, for the user to answer (direction = attribution).
    for q in questions or []:
        SignalReportArtefact.add_log(
            content=q, team_id=team.id, report_id=report_id, attribution=ArtefactAttribution.from_task(str(task.id))
        )
    # User-attributed: feedback FROM the human, for the owner scout to act on and answer.
    for f in feedback or []:
        SignalReportArtefact.add_log(content=f, team_id=team.id, report_id=report_id, attribution=attribution)
    append_task_run_artefact(
        team_id=team.id, report_id=report_id, product="signals", type="planning", task_id=str(task.id)
    )
    print(f"seeded: {title} -> {report_id}")  # noqa: T201
    return report_id


def main() -> None:
    team = Team.objects.get(id=TEAM_ID)
    user = User.objects.filter(is_active=True).order_by("id").first()
    assert user is not None

    _seed_plan(
        team=team,
        user=user,
        title="Plan: burndown chart widget for dashboards",
        summary=(
            "Add a burndown chart widget type to dashboards, so sprint-style progress can be tracked "
            "against error-tracking issue counts. Widget config picks an issue filter and a time "
            "horizon; the chart renders remaining-open counts per day."
        ),
        notes=[
            "## Scope\n\nAgreed with the user: one new `widget_type` (`burndown_chart`) in the widget "
            "registry, config = `{issue_filter, horizon_days}`. No new backend model — the widget "
            "queries error tracking through the existing widget query runner.",
            "## Open questions\n\n- Should closed-then-reopened issues count as new scope?\n- Default "
            "horizon: 14 days (user preference).",
        ],
        code_refs=[
            CodeReference(
                file_path="products/dashboards/backend/widget_specs/error_tracking_list.py",
                start_line=1,
                end_line=12,
                contents="# (seeded example) widget spec registration for error_tracking_list\n...",
                relevance_note="Existing widget spec to model the burndown widget on.",
            )
        ],
        created_ago=timedelta(hours=2),
        questions=[
            QuestionArtefact(
                question="Should closed-then-reopened issues count as **new scope** in the burndown, or stay "
                "attributed to the original scope line?"
            ),
            QuestionArtefact(
                question="Is a 14-day default horizon right, or should the widget infer it from the issue filter?"
            ),
            QuestionArtefact(
                question="Which dashboard should the first burndown widget land on?",
                answer="The team sprint dashboard — pin it top-right.",
                answered=True,
            ),
        ],
    )

    _seed_plan(
        team=team,
        user=user,
        title="Plan: self-serve data deletion requests",
        summary=(
            "Let end users file GDPR deletion requests from the account page, tracked as a queue with "
            "a 30-day SLA. Backend queue model + Celery worker that calls the deletion APIs, plus an "
            "admin review list."
        ),
        notes=[
            "## Progress\n\nFirst implementation PR merged (queue model + API). Worker and admin list "
            "outstanding — next agent pass should pick up the worker.",
        ],
        code_refs=[],
        created_ago=timedelta(days=3),
        questions=[
            QuestionArtefact(
                question="Should the deletion worker hard-delete ClickHouse events too, or only Postgres person data in v1?"
            ),
        ],
        feedback=[
            QuestionArtefact(
                question="Legal wants the SLA surfaced in the request confirmation email — can the next pass add that?"
            ),
        ],
    )


if __name__ == "__main__":
    main()
