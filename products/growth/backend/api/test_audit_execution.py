from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.growth.backend.audit_execution import create_audit_task, finish_account_audit
from products.growth.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.growth.backend.tasks import reconcile_account_audits
from products.skills.backend.facade.api import SkillPrompt
from products.tasks.backend.facade import api as tasks_facade


@override_settings(SITE_URL="http://testserver")
@time_machine.travel("2026-09-01T12:00:00Z", tick=False)
class TestAuditExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.run_id = uuid4()
        credential = AccountAuditCredential.objects.create(
            owner=self.user, workflow_id=uuid4(), signing_secret="unused"
        )
        self.admission = AccountAuditAdmission.objects.for_team(self.team.id).create(
            credential=credential,
            webhook_id="delivery",
            organization_id=self.organization.id,
            team_id=self.team.id,
            task_run_id=self.run_id,
            reason="testing",
            skill_name="custom-audit",
        )
        self.task_run = SimpleNamespace(
            id=self.run_id,
            is_terminal=True,
            status="completed",
            task_origin_product="onboarding_audit",
            created_by_id=self.user.id,
            created_by_distinct_id=self.user.distinct_id,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
            state={"audit_notebook_short_id": "audit123"},
            output={"notebook_short_id": "audit123"},
        )
        self.notebook = SimpleNamespace(
            created_by_id=self.user.id,
            content={
                "type": "doc",
                "content": [{"type": "ph-markdown-notebook", "attrs": {"markdown": "# Audit\n\nFindings."}}],
            },
        )
        self.read_run = patch(
            "products.growth.backend.audit_execution.tasks_facade.get_task_run", return_value=self.task_run
        ).start()
        self.read_notebook = patch(
            "products.growth.backend.audit_execution.notebooks_facade.get_notebook", return_value=self.notebook
        ).start()
        self.cost = patch(
            "products.growth.backend.audit_execution.get_task_run_cost", return_value=SimpleNamespace(token_cost=27)
        ).start()
        self.capture = (
            patch("products.growth.backend.audit_execution.ph_scoped_capture")
            .start()
            .return_value.__enter__.return_value
        )
        self.addCleanup(patch.stopall)

    def finish(self) -> None:
        finish_account_audit(team_id=self.team.id, task_run_id=self.run_id)
        self.admission.refresh_from_db()

    @parameterized.expand([(0,), (27,), (None,)])
    def test_emits_verified_result_with_native_cost_once(self, token_cost: int | None) -> None:
        self.cost.return_value.token_cost = token_cost
        self.finish()
        self.finish()
        self.capture.assert_called_once()
        event = self.capture.call_args.kwargs
        self.assertEqual(event["event"], "onboarding_audit_finished")
        self.assertEqual(
            event["properties"],
            {
                "organization_id": str(self.organization.id),
                "team_id": self.team.id,
                "notebook_url": f"http://testserver/project/{self.team.id}/notebooks/audit123",
                "reason": "testing",
                "skill_name": "custom-audit",
                "token_cost_cents": token_cost,
                "$insert_id": f"account-audit-finished-{self.run_id}",
            },
        )
        self.assertIsNotNone(self.admission.finalized_at)

    @parameterized.expand([("failed",), ("cancelled",), ("in_progress",)])
    def test_no_success_event_for_other_statuses(self, status: str) -> None:
        self.task_run.status = status
        self.task_run.is_terminal = status != "in_progress"
        self.finish()
        self.capture.assert_not_called()
        self.assertEqual(self.admission.finalized_at is not None, self.task_run.is_terminal)

    @parameterized.expand(
        [
            ("empty",),
            ("heading",),
            ("malformed",),
            ("missing",),
            ("wrong_output",),
            ("wrong_creator",),
            ("wrong_origin",),
            ("no_consent",),
        ]
    )
    def test_rejects_unverified_results(self, problem: str) -> None:
        self.task_run.completed_at -= timedelta(minutes=4)
        if problem == "empty":
            self.notebook.content = {"type": "doc", "content": []}
        elif problem == "heading":
            self.notebook.content["content"][0]["attrs"]["markdown"] = "# Audit"
        elif problem == "malformed":
            self.notebook.content = {"type": "ph-markdown-notebook", "attrs": {"markdown": "Findings."}}
        elif problem == "missing":
            self.read_notebook.return_value = None
        elif problem == "wrong_output":
            self.task_run.output = {"notebook_short_id": "another"}
        elif problem == "wrong_creator":
            self.notebook.created_by_id = self.user.id + 1
        elif problem == "wrong_origin":
            self.task_run.task_origin_product = "user_created"
        else:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.finish()
        self.capture.assert_not_called()
        self.assertIsNotNone(self.admission.finalized_at)

    @parameterized.expand([(False,), (True,)])
    def test_waits_for_accounting_then_emits_settled_or_unavailable_cost(self, expires: bool) -> None:
        self.task_run.state["unprocessed_request_ids"] = ["request-1"]
        self.finish()
        self.assertIsNone(self.admission.finalized_at)
        self.capture.assert_not_called()
        if expires:
            self.task_run.completed_at -= timedelta(minutes=3)
            self.cost.return_value.token_cost = None
        else:
            self.task_run.state["unprocessed_request_ids"] = []
        self.finish()
        self.assertEqual(self.capture.call_args.kwargs["properties"]["token_cost_cents"], None if expires else 27)

    def test_retries_capture_failure_and_recovers_missed_notifications(self) -> None:
        self.capture.side_effect = RuntimeError("capture unavailable")
        with self.assertRaises(RuntimeError):
            self.finish()
        self.admission.refresh_from_db()
        self.assertIsNone(self.admission.finalized_at)
        self.capture.side_effect = None
        with patch("products.growth.backend.tasks.finalize_account_audit.delay") as enqueue:
            reconcile_account_audits()
        enqueue.assert_called_once_with(self.team.id, str(self.run_id))
        self.finish()
        self.assertIsNotNone(self.admission.finalized_at)

    def test_native_run_save_schedules_completion_only_after_commit(self) -> None:
        with (
            patch("products.growth.backend.audit_execution.tasks_facade.create_and_run_task") as create,
            patch("products.growth.backend.tasks.finalize_account_audit.delay") as enqueue,
        ):
            create.return_value = SimpleNamespace(latest_run=SimpleNamespace(id=uuid4()))
            run_id = create_audit_task(
                team_id=self.team.id, user_id=self.user.id, skill=SkillPrompt(body="Audit.", version=1)
            )
            kwargs = create.call_args.kwargs
            self.assertEqual(run_id, create.return_value.latest_run.id)
            self.assertFalse(kwargs["create_pr"])
            self.assertTrue(kwargs["internal"])
            self.assertIsNone(kwargs["repository"])
            self.assertEqual(kwargs["sandbox_timeout_seconds"], 10800)
            self.assertEqual(
                kwargs["posthog_mcp_scopes"],
                ["user:read", "query:read", "insight:read", "notebook:read", "notebook:write"],
            )
            self.assertEqual(kwargs["extra_run_state"]["audit_skill_version"], 1)
            self.assertIn(kwargs["extra_run_state"]["audit_notebook_short_id"], kwargs["description"])
        with patch("products.growth.backend.tasks.finalize_account_audit.delay") as enqueue:
            created = tasks_facade.create_and_run_task(
                team=self.team,
                user_id=self.user.id,
                title="Audit",
                description="Audit.",
                origin_product=tasks_facade.TaskOriginProduct.ONBOARDING_AUDIT,
                internal=True,
                create_pr=False,
                start_workflow=False,
                extra_run_state={"audit_notebook_short_id": "audit123"},
            )
            assert created.latest_run is not None
            from products.tasks.backend.models import TaskRun

            run = TaskRun.objects.get(id=created.latest_run.id)
            with self.captureOnCommitCallbacks(execute=True):
                run.status = "completed"
                run.save(update_fields=["status"])
                enqueue.assert_not_called()
            enqueue.assert_called_once_with(self.team.id, str(run.id))
            enqueue.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError):
                    with transaction.atomic():
                        run.save(update_fields=["status"])
                        raise RuntimeError("rollback")
            enqueue.assert_not_called()
