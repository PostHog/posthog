from typing import Any

from pydantic import BaseModel, Field
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import OrganizationMembership, Team, User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.utils import close_db_connections
from posthog.utils import absolute_uri, get_instance_region

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.notebooks.backend.facade import api as notebooks_facade
from products.skills.backend.facade import api as skills_facade
from products.tasks.backend.facade import api as tasks_facade


class AccountAuditOutput(BaseModel):
    notebook_short_id: str = Field(min_length=1)


@frozen
class AccountAuditStartInput:
    organization_id: str
    team_id: int
    user_id: int
    origin_key: str


@frozen
class TaskRunStatusInput:
    team_id: int
    task_run_id: str


@frozen
class AccountAuditFinishInput:
    organization_id: str
    team_id: int
    user_id: int
    task_run_id: str
    notebook_short_id: str


@frozen
class AccountAuditTaskRunStatus:
    status: str
    terminal: bool
    notebook_short_id: str | None = None


def _notebook_short_id(output: dict[str, Any] | None) -> str | None:
    if output is None:
        return None
    try:
        return AccountAuditOutput.model_validate(output).notebook_short_id
    except ValueError:
        return None


@activity.defn
@close_db_connections
def start_account_audit_activity(input: AccountAuditStartInput) -> str:
    team = (
        Team.objects.select_related("organization")
        .filter(id=input.team_id, organization_id=input.organization_id)
        .first()
    )
    if team is None:
        raise ValueError("Project does not belong to the organization")
    if not team.organization.is_ai_data_processing_approved:
        raise PermissionError("Organization has not approved AI data processing")

    user = User.objects.filter(id=input.user_id, is_active=True).first()
    if (
        user is None
        or not OrganizationMembership.objects.filter(
            organization_id=input.organization_id, user_id=input.user_id
        ).exists()
    ):
        raise PermissionError("User is not an active organization member")
    if not UserAccessControl(user=user, team=team).check_access_level_for_object(team, "member"):
        raise PermissionError("User cannot access the project")

    origin_key = input.origin_key
    existing = tasks_facade.get_task_by_origin_key(team.id, origin_key)
    if existing is not None:
        if existing.origin_product != tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT or existing.latest_run is None:
            raise RuntimeError("Existing account audit task is invalid")
        return str(existing.latest_run.id)

    skill = skills_facade.get_skill_prompt(team_id=2, skill_name="onboarding-account-audit")
    if skill is None or not skill.body.strip():
        raise RuntimeError("Account audit skill is unavailable")

    created = tasks_facade.create_and_run_task(
        team=team,
        title="Account audit",
        description=(
            f"{skill.body}\n\nThe audited project ID is {team.id}. "
            "Use this project for every query and notebook. Create a notebook with PostHog MCP. "
            "Read the saved notebook before you return its short ID as notebook_short_id."
        ),
        origin_product=tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT,
        user_id=input.user_id,
        repository=None,
        create_pr=False,
        internal=True,
        origin_key=origin_key,
        posthog_mcp_scopes=["user:read", "query:read", "insight:read", "notebook:read", "notebook:write"],
        model="claude-sonnet-5",
        output_schema=AccountAuditOutput,
        extra_run_state={"audit_skill_name": "onboarding-account-audit", "audit_skill_version": skill.version},
    )
    if created.latest_run is None:
        raise RuntimeError("Account audit task was created without a run")
    return str(created.latest_run.id)


@activity.defn
@close_db_connections
def get_account_audit_task_run_status_activity(input: TaskRunStatusInput) -> AccountAuditTaskRunStatus:
    run = tasks_facade.get_task_run(input.task_run_id, team_id=input.team_id)
    if run is None:
        raise RuntimeError("Account audit task run was not found")
    return AccountAuditTaskRunStatus(
        status=run.status,
        terminal=run.is_terminal,
        notebook_short_id=_notebook_short_id(run.output)
        if run.status == tasks_facade.TaskRunStatus.COMPLETED
        else None,
    )


@activity.defn
@close_db_connections
def finish_account_audit_activity(input: AccountAuditFinishInput) -> str:
    run = tasks_facade.get_task_run(input.task_run_id, team_id=input.team_id)
    if (
        run is None
        or run.status != tasks_facade.TaskRunStatus.COMPLETED
        or run.task_origin_product != tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT
        or run.created_by_id != input.user_id
        or _notebook_short_id(run.output) != input.notebook_short_id
    ):
        raise RuntimeError("Account audit task output could not be verified")

    notebook = notebooks_facade.get_notebook(input.team_id, input.notebook_short_id)
    if (
        notebook is None
        or run.created_at is None
        or notebook.created_by_id != input.user_id
        or notebook.created_at < run.created_at
        or not any(
            line.strip() and not line.lstrip().startswith("#") for line in (notebook.text_content or "").splitlines()
        )
    ):
        raise RuntimeError("Account audit notebook could not be verified")

    team = (
        Team.objects.select_related("organization")
        .filter(id=input.team_id, organization_id=input.organization_id)
        .first()
    )
    user = User.objects.filter(id=input.user_id).first()
    if team is None or user is None or not user.distinct_id or not team.organization.is_ai_data_processing_approved:
        raise RuntimeError("Account audit attribution or AI approval is unavailable")

    notebook_url = absolute_uri(f"/project/{input.team_id}/notebooks/{notebook.short_id}")
    with ph_scoped_capture(region=get_instance_region() or "US", raise_on_error=True) as capture:
        capture(
            distinct_id=str(user.distinct_id),
            event="audit_finished",
            properties={
                "organization_id": input.organization_id,
                "team_id": input.team_id,
                "notebook_url": notebook_url,
                "$insert_id": f"account-audit-finished-{input.task_run_id}",
            },
            groups=groups(team.organization, team),
        )
    return notebook_url


ACTIVITIES = [
    start_account_audit_activity,
    get_account_audit_task_run_status_activity,
    finish_account_audit_activity,
]
