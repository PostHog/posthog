import logging
from datetime import timedelta
from uuid import UUID

from django.utils import timezone

from pydantic import BaseModel, Field

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.utils import absolute_uri, get_instance_region

from products.growth.backend.models import AccountAuditAdmission
from products.notebooks.backend.facade import api as notebooks_facade
from products.notebooks.backend.facade.content import convert_notebook_content_to_markdown
from products.skills.backend.facade.api import SkillPrompt
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import get_task_run_cost

logger = logging.getLogger(__name__)
COMPLETION_GRACE = timedelta(minutes=3)


class AccountAuditOutput(BaseModel):
    notebook_short_id: str = Field(min_length=1)


def create_audit_task(*, team_id: int, user_id: int, skill: SkillPrompt) -> UUID:
    notebook = notebooks_facade.create_notebook(
        team_id,
        title="Account audit",
        content={"type": "doc", "content": []},
        text_content="",
        created_by_id=user_id,
        last_modified_by_id=user_id,
        creation_source="server",
    )
    notebook_short_id = notebook.short_id
    created = tasks_facade.create_and_run_task(
        team=Team.objects.get(id=team_id),
        title="Account audit",
        description=(
            f"{skill.body}\n\nThe audited project ID is {team_id}. "
            f"Use this project for every query. Save the audit to the existing notebook {notebook_short_id} "
            "with PostHog MCP, even if the skill asks you to create a notebook. "
            "Read the saved notebook before you return its short ID as notebook_short_id."
        ),
        origin_product=tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT,
        user_id=user_id,
        repository=None,
        create_pr=False,
        internal=True,
        posthog_mcp_scopes=["user:read", "query:read", "insight:read", "notebook:read", "notebook:write"],
        model="claude-sonnet-5",
        output_schema=AccountAuditOutput,
        sandbox_timeout_seconds=3 * 60 * 60,
        extra_run_state={"audit_notebook_short_id": notebook_short_id, "audit_skill_version": skill.version},
    )
    if created.latest_run is None:
        raise RuntimeError("Account audit task was created without a run")
    return created.latest_run.id


def finish_account_audit(*, team_id: int, task_run_id: UUID) -> None:
    admission = (
        AccountAuditAdmission.objects.for_team(team_id)
        .filter(task_run_id=task_run_id, finalized_at__isnull=True)
        .first()
    )
    if admission is None:
        return
    run = tasks_facade.get_task_run(str(task_run_id), team_id=team_id)
    if run is None:
        AccountAuditAdmission.objects.for_team(team_id).filter(pk=admission.pk).update(finalized_at=timezone.now())
        return
    if not run.is_terminal:
        return
    if run.status == tasks_facade.TaskRunStatus.COMPLETED:
        now = timezone.now()
        settling = now < (run.completed_at or run.updated_at or admission.created_at) + COMPLETION_GRACE
        if settling and run.state.get("unprocessed_request_ids") and not run.state.get("token_cost_incomplete"):
            return
        notebook_id = run.state.get("audit_notebook_short_id")
        notebook = notebooks_facade.get_notebook(team_id, notebook_id) if isinstance(notebook_id, str) else None
        valid = (
            run.task_origin_product == tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT
            and (run.output or {}).get("notebook_short_id") == notebook_id
            and notebook is not None
            and run.created_by_id is not None
            and notebook.created_by_id == run.created_by_id
            and any(
                line.strip() and not line.lstrip().startswith("#")
                for line in convert_notebook_content_to_markdown(notebook.content).splitlines()
            )
        )
        if not valid and settling:
            return
        team = (
            Team.objects.select_related("organization")
            .filter(id=team_id, organization_id=admission.organization_id)
            .first()
        )
        if valid and run.created_by_distinct_id and team and team.organization.is_ai_data_processing_approved:
            cost = get_task_run_cost(run_id=task_run_id, team_id=team_id)
            with ph_scoped_capture(region=get_instance_region() or "US", raise_on_error=True) as capture:
                capture(
                    distinct_id=run.created_by_distinct_id,
                    event="onboarding_audit_finished",
                    properties={
                        "organization_id": str(admission.organization_id),
                        "team_id": team_id,
                        "notebook_url": absolute_uri(f"/project/{team_id}/notebooks/{notebook_id}"),
                        "reason": admission.reason,
                        "skill_name": admission.skill_name,
                        "token_cost_cents": cost.token_cost,
                        "$insert_id": f"account-audit-finished-{task_run_id}",
                    },
                    groups=groups(team.organization, team),
                )
        else:
            logger.warning("account_audit_result_rejected", extra={"task_run_id": str(task_run_id)})
    AccountAuditAdmission.objects.for_team(team_id).filter(pk=admission.pk).update(finalized_at=timezone.now())
