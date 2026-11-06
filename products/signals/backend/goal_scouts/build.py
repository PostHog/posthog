from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import APIException, ValidationError

from posthog.models import Team, User

from products.signals.backend.artefact_schemas import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.auto_start import (
    AutostartSkip,
    ImplementationReportContent,
    build_implementation_task_description,
    create_implementation_task_if_absent,
)
from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.usage import task_run_usage_limited

from ..models import SignalReport, SignalScoutConfig, SignalScoutGoal, SignalScoutGoalIdea, SignalTeamConfig
from .ideas import IDEA_TAG, OWNER, PROPOSED, TRACKING_TAG, IdeaView, goal_ideas, open_row
from .scout import goal_summary, history
from .spend import goal_spend
from .tracking import GOAL_TASK_RULES, tracking_task

RUNNER_SOURCE = "goal"
REVIEW_STATES = ("open", "draft", "unknown")
CLEANUP_RETRY_STATES = ("failed", "cancelled")

Stage = SignalScoutGoalIdea.Stage
Kind = SignalScoutGoalIdea.Kind


def lock_goal(goal: SignalScoutGoal) -> SignalScoutGoal:
    return SignalScoutGoal.objects.for_team(goal.team_id).select_for_update().select_related("config").get(pk=goal.pk)


def file_report(goal: SignalScoutGoal, *, title: str, summary: str, tags: list[str]) -> SignalReport:
    return SignalReport.objects.create(
        team_id=goal.team_id, status=SignalReport.Status.READY, title=title[:500], summary=summary, tags=tags
    )


def next_number(goal: SignalScoutGoal, kind: str) -> int:
    numbers = (
        SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(goal=goal, kind=kind).values_list("number", flat=True)
    )
    return max(numbers, default=0) + 1


def launch(goal: SignalScoutGoal, report: SignalReport, user: User, work_instructions: str) -> str:
    repositories = goal.config.repositories or []
    if not repositories:
        return "Choose a repository for this goal."
    repository = repositories[0]
    team = Team.objects.select_related("organization").get(id=goal.team_id)
    team_config = SignalTeamConfig.objects.filter(team_id=goal.team_id).first()
    description = build_implementation_task_description(
        report_id=str(report.id),
        team_id=goal.team_id,
        summary=report.summary or "",
        repository=repository,
        priority=None,
        work_instructions=work_instructions,
    )
    try:
        created = create_implementation_task_if_absent(
            team_id=goal.team_id,
            report_id=str(report.id),
            title=report.title or "Goal work",
            description=description,
            expected_content=ImplementationReportContent.from_report(report),
            user_id=user.id,
            repository=repository,
            base_branch=team_config.base_branch_for(repository) if team_config else None,
            free_trial_enabled=self_driving_free_trial_enabled(team),
            runner_source=RUNNER_SOURCE,
        )
    except APIException as error:
        return str(error.detail)
    if isinstance(created, AutostartSkip):
        return created.detail
    return "" if created else "The task did not start."


def start_tracking(goal: SignalScoutGoal, user: User) -> SignalScoutGoalIdea:
    with transaction.atomic():
        locked = lock_goal(goal)
        SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(
            goal=locked, kind=Kind.TRACKING, stage__in=SignalScoutGoalIdea.OPEN_STAGES
        ).update(stage=Stage.DROPPED, note="The measure changed.", finished_at=timezone.now())
        report = file_report(
            locked,
            title=f"Check how {locked.metric_name or 'the goal'} is measured",
            summary=f"{goal_summary(locked)}\n\n{tracking_task(locked)}",
            tags=[TRACKING_TAG],
        )
        idea = SignalScoutGoalIdea.objects.create(
            team_id=locked.team_id,
            goal=locked,
            report=report,
            kind=Kind.TRACKING,
            number=next_number(locked, Kind.TRACKING),
            stage=Stage.BUILDING,
            note="Checking the tracking code.",
            chosen_by=user,
        )
    note = launch(locked, report, user, GOAL_TASK_RULES)
    if note:
        idea.stage = Stage.STUCK
        idea.note = note
        idea.save(update_fields=["stage", "note", "updated_at"])
    return idea


def idea_task(goal: SignalScoutGoal, views: list[IdeaView], view: IdeaView, flag_key: str, plan: dict) -> str:
    days = f" Plan to run it for {plan['days']} days." if plan.get("days") else ""
    return f"""{goal_summary(goal)}

## What we tried
{history(views)}

## Task
Turn this idea into a pull request and an experiment.
Idea: {view.title}

1. Implement the change in the repository behind the feature flag `{flag_key}`. Users without the flag see today's behavior. Keep the diff small and add focused tests.
   If people can see the change around sign-up or login, turn on "Persist flag across authentication steps" (ensure_experience_continuity) for the flag, so each person keeps one variant.
2. Open one pull request. Mention the flag key and the experiment in its description.
3. In PostHog, create an experiment that uses the feature flag `{flag_key}` with a control and a test variant. Use the saved insight {goal.insight_short_id} as the experiment's primary metric, and each guardrail as a secondary metric.{days}
4. Launch the experiment. Nobody is exposed until the pull request is merged and deployed, so launching now is safe.
End with a short summary of the change and the experiment.

{GOAL_TASK_RULES}"""


def build_refusal(goal: SignalScoutGoal, views: list[IdeaView], spent_cents: int) -> str:
    if open_row(views) is not None:
        return "Wait for the current idea's result."
    if goal.config.status == SignalScoutConfig.Status.PAUSED_BY_USER:
        return "Resume the goal to build an idea."
    if goal.status == SignalScoutGoal.Status.SETTING_UP:
        return "The goal is still setting up."
    if goal.status == SignalScoutGoal.Status.SPENT or spent_cents >= goal.budget_cents:
        return "The budget is used. Add budget to build an idea."
    if goal.status != SignalScoutGoal.Status.RUNNING:
        return "Ideas can only be built while the goal runs."
    return ""


def build_idea(team: Team, user: User, goal: SignalScoutGoal, work_id: str, plan: dict) -> SignalScoutGoalIdea:
    if task_run_usage_limited(user, goal.team_id):
        raise ValidationError("The project's task usage limit is reached.")
    tasks_facade.enforce_self_driving_pr_quota(team, stage="manual_create")
    with transaction.atomic():
        locked = lock_goal(goal)
        views = goal_ideas(locked)
        view = next((item for item in views if item.id == work_id), None)
        if view is None or view.stage != PROPOSED or view.kind != Kind.IDEA:
            raise ValidationError("This idea cannot be built.")
        if refusal := build_refusal(locked, views, goal_spend(locked).spent_cents):
            raise ValidationError(refusal)
        report = (
            SignalReport.objects.get(team_id=locked.team_id, id=view.report_id)
            if view.report_id
            else file_report(
                locked,
                title=f"Owner idea {view.owner_number}: {view.title}",
                summary=view.title,
                tags=[IDEA_TAG, f"owner-idea-{view.owner_number}"],
            )
        )
        number = next_number(locked, Kind.IDEA)
        flag_key = f"goal-{locked.pk.hex[-8:]}-{number}"
        idea = SignalScoutGoalIdea.objects.create(
            team_id=locked.team_id,
            goal=locked,
            report=report,
            kind=Kind.IDEA,
            number=number,
            flag_key=flag_key,
            stage=Stage.BUILDING,
            plan=stage_plan(plan, view),
            note="Building the pull request and the experiment.",
            chosen_by=user,
        )
        if note := launch(locked, report, user, idea_task(locked, views, view, flag_key, plan)):
            raise ValidationError(note)
    return idea


def stage_plan(plan: dict, view: IdeaView) -> dict:
    return {**plan, "audience": plan.get("audience") or view.audience, "owner_idea": view.source == OWNER}


def retry(user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea) -> SignalScoutGoalIdea:
    if idea.stage != Stage.STUCK:
        raise ValidationError("Only stuck work can be retried.")
    pr = fetch_implementation_pr_state_for_reports([str(idea.report_id)], team_id=goal.team_id).get(str(idea.report_id))
    if idea.merged_at is not None:
        resume = Stage.LIVE if idea.kind == Kind.IDEA else Stage.DONE
    elif pr is not None and pr.state in REVIEW_STATES and not pr.merged:
        resume = Stage.REVIEW
    else:
        resume = Stage.BUILDING
        if note := resume_task(user, goal, idea):
            raise ValidationError(note)
    idea.stage = resume
    idea.note = "Trying again."
    idea.save(update_fields=["stage", "note", "updated_at"])
    return idea


def retry_cleanup(user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea) -> None:
    if idea.cleanup_task_id is None:
        raise ValidationError("This idea has no flag cleanup task.")
    task_id = str(idea.cleanup_task_id)
    run = tasks_facade.get_latest_run_by_task([task_id]).get(task_id)
    if run is None or run.status not in CLEANUP_RETRY_STATES:
        raise ValidationError("Only a flag cleanup that failed can be tried again.")
    result = tasks_facade.run_task(task_id, goal.team_id, user.id, validated_data={"mode": "background"})
    if result is None or result.error is not None or result.run_error or result.run_id is None:
        raise ValidationError((result.run_error if result else "") or "The flag cleanup could not start again.")


def resume_task(user: User, goal: SignalScoutGoal, idea: SignalScoutGoalIdea) -> str:
    entries = SignalReport.associated_task_runs(
        report_id=str(idea.report_id), team_id=goal.team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
    )
    report = SignalReport.objects.get(team_id=goal.team_id, id=idea.report_id)
    if not entries:
        return launch(goal, report, user, GOAL_TASK_RULES)
    task_id = entries[-1].task_id
    runs = tasks_facade.get_signal_report_implementation_runs(goal.team_id, str(idea.report_id), [task_id])
    if runs and not runs[0].is_terminal:
        return "The task is still running. Wait for it to end, then try again."
    team = Team.objects.select_related("organization").get(id=goal.team_id)
    result = tasks_facade.run_task(
        task_id,
        goal.team_id,
        user.id,
        free_trial_enabled=self_driving_free_trial_enabled(team),
        validated_data={
            "mode": "background",
            "run_source": "signal_report",
            **({"resume_from_run_id": str(runs[0].id)} if runs else {}),
            "pending_user_message": f"The last attempt stopped: {idea.note}\n\nTry again and finish the task.",
        },
    )
    if result is None or result.error is not None or result.run_error or result.run_id is None:
        return (result.run_error if result else "") or "The task could not start again."
    record_implementation_task(
        team_id=goal.team_id, report_id=str(idea.report_id), task_id=str(task_id), run_id=str(result.run_id)
    )
    return ""
