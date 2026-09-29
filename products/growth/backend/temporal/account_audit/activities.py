import hashlib
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction

from asgiref.sync import async_to_sync
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
from products.notebooks.backend.facade.content import convert_notebook_content_to_markdown
from products.skills.backend.facade import api as skills_facade
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import get_task_run_cost
from products.tasks.backend.facade.cancellation import cancel_task_run


class AccountAuditOutput(BaseModel):
    notebook_short_id: str = Field(min_length=1)


@frozen
class AccountAuditStartInput:
    organization_id: str
    team_id: int
    user_id: int
    origin_key: str
    reason: str = ""
    skill_name: str = "onboarding-account-audit"


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
    reason: str = ""
    skill_name: str = "onboarding-account-audit"


@frozen
class AccountAuditTaskRunStatus:
    status: str
    terminal: bool
    notebook_short_id: str | None = None
    cost_pending: bool = False


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

    skill = skills_facade.get_skill_prompt(
        team_id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID, skill_name=input.skill_name
    )
    if skill is None or not skill.body.strip():
        raise RuntimeError("Account audit skill is unavailable")

    notebook_short_id = hashlib.sha256(origin_key.encode()).hexdigest()[:12]
    if notebooks_facade.get_notebook(team.id, notebook_short_id) is None:
        async_to_sync(notebooks_facade.aupsert_notebook)(
            team.id,
            notebook_short_id,
            title="Account audit",
            content={"type": "doc", "content": []},
            text_content="",
            created_by_id=input.user_id,
            last_modified_by_id=input.user_id,
            creation_source="server",
        )

    with transaction.atomic():
        created = tasks_facade.create_and_run_task(
            team=team,
            title="Account audit",
            description=(
                f"{skill.body}\n\nThe audited project ID is {team.id}. "
                f"Use this project for every query. Save the audit to the existing notebook {notebook_short_id} "
                "with PostHog MCP, even if the skill asks you to create a notebook. "
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
            extra_run_state={
                "audit_notebook_short_id": notebook_short_id,
                "audit_reason": input.reason,
                "audit_skill_name": input.skill_name,
                "audit_skill_version": skill.version,
            },
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
        cost_pending=bool(run.state.get("unprocessed_request_ids"))
        and not run.state.get("token_cost_incomplete", False),
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
        or run.state.get("audit_notebook_short_id") != input.notebook_short_id
    ):
        raise RuntimeError("Account audit task output could not be verified")

    notebook = notebooks_facade.get_notebook(input.team_id, input.notebook_short_id)
    if (
        notebook is None
        or notebook.created_by_id != input.user_id
        or not any(
            line.strip() and not line.lstrip().startswith("#")
            for line in convert_notebook_content_to_markdown(notebook.content).splitlines()
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

    cost = get_task_run_cost(run_id=UUID(input.task_run_id), team_id=input.team_id)
    notebook_url = absolute_uri(f"/project/{input.team_id}/notebooks/{notebook.short_id}")
    with ph_scoped_capture(region=get_instance_region() or "US", raise_on_error=True) as capture:
        capture(
            distinct_id=str(user.distinct_id),
            event="onboarding_audit_finished",
            properties={
                "organization_id": input.organization_id,
                "team_id": input.team_id,
                "notebook_url": notebook_url,
                "reason": input.reason,
                "skill_name": input.skill_name,
                "token_cost": cost.token_cost,
                "$insert_id": f"account-audit-finished-{input.task_run_id}",
            },
            groups=groups(team.organization, team),
        )
    return notebook_url


@activity.defn
@close_db_connections
def cancel_account_audit_task_activity(input: AccountAuditStartInput) -> None:
    task = tasks_facade.get_task_by_origin_key(input.team_id, input.origin_key)
    if task is None or task.latest_run is None:
        return
    if task.origin_product != tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT:
        raise ValueError("Task is not an account audit")
    outcome, _ = cancel_task_run(
        task.latest_run.id,
        task.id,
        input.team_id,
        reason="Account audit workflow stopped before completion",
        source="account_audit",
    )
    if outcome == "unavailable":
        raise RuntimeError("Could not cancel the account audit task")


ACTIVITIES = [
    cancel_account_audit_task_activity,
    start_account_audit_activity,
    get_account_audit_task_run_status_activity,
    finish_account_audit_activity,
]
