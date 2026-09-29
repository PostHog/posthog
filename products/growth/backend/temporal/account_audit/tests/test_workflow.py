from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.growth.backend.facade.api import start_account_audit
from products.growth.backend.temporal.account_audit.activities import (
    AccountAuditFinishInput,
    AccountAuditStartInput,
    AccountAuditTaskRunStatus,
    TaskRunStatusInput,
    finish_account_audit_activity,
    start_account_audit_activity,
)
from products.growth.backend.temporal.account_audit.workflow import AccountAuditWorkflow, AccountAuditWorkflowInput


@pytest.mark.asyncio
async def test_facade_dispatches_to_signals_queue() -> None:
    client = SimpleNamespace(start_workflow=AsyncMock())
    with patch("products.growth.backend.facade.api.async_connect", new_callable=AsyncMock, return_value=client):
        workflow_id = await start_account_audit(
            organization_id="org-1",
            team_id=4,
            user_id=5,
            reason="testing",
            skill_name="custom-audit",
            workflow_id="reserved-audit-workflow",
        )

    assert workflow_id == "reserved-audit-workflow"
    assert client.start_workflow.call_args.kwargs["id"] == workflow_id
    from django.conf import settings

    assert client.start_workflow.call_args.kwargs["task_queue"] == settings.VIDEO_EXPORT_TASK_QUEUE
    assert client.start_workflow.call_args.kwargs["id_reuse_policy"].name == "REJECT_DUPLICATE"
    assert client.start_workflow.call_args.args[1] == AccountAuditWorkflowInput(
        organization_id="org-1", team_id=4, user_id=5, reason="testing", skill_name="custom-audit"
    )


@pytest.mark.asyncio
async def test_workflow_polls_until_the_task_creates_a_notebook() -> None:
    origin_keys: list[str] = []
    statuses = iter(
        [
            AccountAuditTaskRunStatus(status="in_progress", terminal=False),
            AccountAuditTaskRunStatus(status="completed", terminal=True, notebook_short_id="audit123"),
        ]
    )

    @activity.defn(name="start_account_audit_activity")
    async def start(input: AccountAuditStartInput) -> str:
        assert input.reason == "testing"
        assert input.skill_name == "custom-audit"
        origin_keys.append(input.origin_key)
        return "run-1"

    @activity.defn(name="get_account_audit_task_run_status_activity")
    async def status(_input: TaskRunStatusInput) -> AccountAuditTaskRunStatus:
        return next(statuses)

    @activity.defn(name="finish_account_audit_activity")
    async def finish(input: AccountAuditFinishInput) -> str:
        assert input.reason == "testing"
        assert input.skill_name == "custom-audit"
        return "http://testserver/project/4/notebooks/audit123"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="account-audit-test",
            workflows=[AccountAuditWorkflow],
            activities=[start, status, finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                AccountAuditWorkflow.run,
                AccountAuditWorkflowInput(
                    organization_id="org-1", team_id=4, user_id=5, reason="testing", skill_name="custom-audit"
                ),
                id=AccountAuditWorkflow.workflow_id_for("org-1"),
                task_queue="account-audit-test",
            )

    assert result == "http://testserver/project/4/notebooks/audit123"
    assert len(origin_keys) == 1
    assert origin_keys[0].startswith("growth-account-audit-org-1:")


class TestStartAccountAuditActivity(SimpleTestCase):
    def test_starts_a_repo_less_task_with_only_audit_scopes(self) -> None:
        team = SimpleNamespace(id=4, organization=SimpleNamespace(is_ai_data_processing_approved=True))
        user = SimpleNamespace(id=5)
        created = SimpleNamespace(latest_run=SimpleNamespace(id=uuid4()))
        user_access = MagicMock()
        user_access.check_access_level_for_object.return_value = True
        skill = SimpleNamespace(body="Create an account audit notebook.", version=1)

        with (
            patch("products.growth.backend.temporal.account_audit.activities.Team.objects") as team_objects,
            patch("products.growth.backend.temporal.account_audit.activities.User.objects") as user_objects,
            patch(
                "products.growth.backend.temporal.account_audit.activities.OrganizationMembership.objects"
            ) as memberships,
            patch(
                "products.growth.backend.temporal.account_audit.activities.UserAccessControl",
                return_value=user_access,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.get_task_by_origin_key",
                return_value=None,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.skills_facade.get_skill_prompt",
                return_value=skill,
            ) as get_skill,
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.create_and_run_task",
                return_value=created,
            ) as create_task,
        ):
            team_objects.select_related.return_value.filter.return_value.first.return_value = team
            user_objects.filter.return_value.first.return_value = user
            memberships.filter.return_value.exists.return_value = True

            run_id = start_account_audit_activity(
                AccountAuditStartInput(
                    organization_id="org-1",
                    team_id=4,
                    user_id=5,
                    origin_key="growth-account-audit-org-1:run-1",
                    reason="testing",
                    skill_name="custom-audit",
                )
            )

        assert run_id == str(created.latest_run.id)
        get_skill.assert_called_once_with(team_id=2, skill_name="custom-audit")
        assert "Audit reason: testing" in create_task.call_args.kwargs["description"]
        assert create_task.call_args.kwargs["repository"] is None
        assert create_task.call_args.kwargs["create_pr"] is False
        assert "The audited project ID is 4." in create_task.call_args.kwargs["description"]
        assert create_task.call_args.kwargs["extra_run_state"] == {
            "audit_reason": "testing",
            "audit_skill_name": "custom-audit",
            "audit_skill_version": 1,
        }
        assert create_task.call_args.kwargs["posthog_mcp_scopes"] == [
            "user:read",
            "query:read",
            "insight:read",
            "notebook:read",
            "notebook:write",
        ]

    def test_missing_skill_does_not_start_a_task(self) -> None:
        team = SimpleNamespace(id=4, organization=SimpleNamespace(is_ai_data_processing_approved=True))
        user_access = MagicMock()
        user_access.check_access_level_for_object.return_value = True
        with (
            patch("products.growth.backend.temporal.account_audit.activities.Team.objects") as team_objects,
            patch("products.growth.backend.temporal.account_audit.activities.User.objects") as user_objects,
            patch(
                "products.growth.backend.temporal.account_audit.activities.OrganizationMembership.objects"
            ) as memberships,
            patch(
                "products.growth.backend.temporal.account_audit.activities.UserAccessControl", return_value=user_access
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.get_task_by_origin_key",
                return_value=None,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.skills_facade.get_skill_prompt",
                return_value=None,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.create_and_run_task"
            ) as create_task,
        ):
            team_objects.select_related.return_value.filter.return_value.first.return_value = team
            user_objects.filter.return_value.first.return_value = SimpleNamespace(id=5)
            memberships.filter.return_value.exists.return_value = True
            with self.assertRaisesRegex(RuntimeError, "skill is unavailable"):
                start_account_audit_activity(
                    AccountAuditStartInput(
                        organization_id="org-1",
                        team_id=4,
                        user_id=5,
                        origin_key="growth-account-audit-org-1:run-1",
                        reason="testing",
                        skill_name="custom-audit",
                    )
                )
            create_task.assert_not_called()

    def test_does_not_capture_when_the_notebook_is_missing(self) -> None:
        now = timezone.now()
        run = SimpleNamespace(
            status="completed",
            task_origin_product="onboarding_audit",
            created_by_id=5,
            output={"notebook_short_id": "missing"},
            created_at=now,
        )
        with (
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.get_task_run",
                return_value=run,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.notebooks_facade.get_notebook",
                return_value=None,
            ),
            patch("products.growth.backend.temporal.account_audit.activities.ph_scoped_capture") as scoped_capture,
        ):
            with self.assertRaisesRegex(RuntimeError, "notebook could not be verified"):
                finish_account_audit_activity(
                    AccountAuditFinishInput(
                        organization_id="org-1",
                        team_id=4,
                        user_id=5,
                        task_run_id="run-1",
                        notebook_short_id="missing",
                    )
                )

        scoped_capture.assert_not_called()

    def test_capture_requires_the_audit_run_and_a_new_notebook_with_content(self) -> None:
        now = timezone.now()
        run = SimpleNamespace(
            status="completed",
            task_origin_product="onboarding_audit",
            created_by_id=5,
            output={"notebook_short_id": "audit123"},
            created_at=now,
        )
        notebook = SimpleNamespace(
            short_id="audit123",
            created_by_id=5,
            created_at=now + timedelta(seconds=1),
            text_content="# Account audit\n\nFindings and next steps.",
        )
        team = SimpleNamespace(id=4, organization=SimpleNamespace(is_ai_data_processing_approved=True))
        user = SimpleNamespace(distinct_id="user-5")
        input = AccountAuditFinishInput(
            organization_id="org-1",
            team_id=4,
            user_id=5,
            task_run_id="run-1",
            notebook_short_id="audit123",
            reason="testing",
            skill_name="custom-audit",
        )
        with (
            patch(
                "products.growth.backend.temporal.account_audit.activities.tasks_facade.get_task_run",
                return_value=run,
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.notebooks_facade.get_notebook",
                return_value=notebook,
            ),
            patch("products.growth.backend.temporal.account_audit.activities.Team.objects") as team_objects,
            patch("products.growth.backend.temporal.account_audit.activities.User.objects") as user_objects,
            patch(
                "products.growth.backend.temporal.account_audit.activities.absolute_uri",
                return_value="https://us.posthog.com/project/4/notebooks/audit123",
            ),
            patch(
                "products.growth.backend.temporal.account_audit.activities.groups",
                return_value={"organization": "org-1"},
            ),
            patch("products.growth.backend.temporal.account_audit.activities.ph_scoped_capture") as scoped_capture,
        ):
            team_objects.select_related.return_value.filter.return_value.first.return_value = team
            user_objects.filter.return_value.first.return_value = user
            result = finish_account_audit_activity(input)
            assert result == "https://us.posthog.com/project/4/notebooks/audit123"
            capture = scoped_capture.return_value.__enter__.return_value
            capture.assert_called_once()
            assert capture.call_args.kwargs["event"] == "onboarding_audit_finished"
            assert capture.call_args.kwargs["properties"] == {
                "organization_id": "org-1",
                "team_id": 4,
                "notebook_url": result,
                "reason": "testing",
                "skill_name": "custom-audit",
                "$insert_id": "account-audit-finished-run-1",
            }

            notebook.created_at = now - timedelta(seconds=1)
            with self.assertRaisesRegex(RuntimeError, "notebook could not be verified"):
                finish_account_audit_activity(input)
            capture.assert_called_once()
