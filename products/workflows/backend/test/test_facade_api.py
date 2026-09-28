from datetime import timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.facade.api import (
    WorkflowAccessDenied,
    WorkflowArchived,
    WorkflowInvalid,
    WorkflowNotFound,
    archive_workflow,
    create_workflow,
    create_workflow_schedule,
    update_workflow_schedule,
)
from products.workflows.backend.models import HogFlow, HogFlowSchedule

DAILY_ONCE = "FREQ=DAILY;COUNT=1"


def _loop_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Weekly account digest",
        "description": "Summarize what changed on each account",
        "status": "active",
        "origin_product": "loops",
        "exit_condition": "exit_only_at_end",
        "variables": [{"key": "summary", "type": "string", "default": ""}],
        "actions": [
            {"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "schedule"}},
            {"id": "exit", "name": "Exit", "type": "exit", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "exit", "type": "continue"}],
        **overrides,
    }


class TestWorkflowsFacade(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.starts_at = (timezone.now() + timedelta(days=1)).replace(microsecond=0)

    def _create_loop(self, **overrides: Any) -> HogFlow:
        dto = create_workflow(team_id=self.team.id, user_id=self.user.id, data=_loop_payload(**overrides))
        return HogFlow.objects.get(id=dto.id)

    def _create_schedule(self, workflow: HogFlow) -> UUID:
        dto = create_workflow_schedule(
            team_id=self.team.id,
            user_id=self.user.id,
            workflow_id=workflow.id,
            rrule=DAILY_ONCE,
            starts_at=self.starts_at,
        )
        return UUID(dto.id)

    def test_create_workflow_creates_an_active_loop_owned_by_the_user(self) -> None:
        dto = create_workflow(team_id=self.team.id, user_id=self.user.id, data=_loop_payload())

        assert dto.status == "active"
        assert dto.name == "Weekly account digest"
        workflow = HogFlow.objects.get(id=dto.id)
        assert workflow.origin_product == "loops"
        assert workflow.created_by_id == self.user.id
        assert workflow.trigger == {"type": "schedule"}

    def test_create_workflow_rejects_a_graph_without_a_trigger(self) -> None:
        payload = _loop_payload(actions=[{"id": "exit", "name": "Exit", "type": "exit", "config": {}}], edges=[])

        with self.assertRaises(WorkflowInvalid) as raised:
            create_workflow(team_id=self.team.id, user_id=self.user.id, data=payload)

        assert "actions" in raised.exception.detail
        assert not HogFlow.objects.filter(team=self.team).exists()

    def test_create_workflow_schedule_adds_a_schedule_for_the_scheduler_to_arm(self) -> None:
        workflow = self._create_loop()

        dto = create_workflow_schedule(
            team_id=self.team.id,
            user_id=self.user.id,
            workflow_id=workflow.id,
            rrule=DAILY_ONCE,
            starts_at=self.starts_at,
        )

        assert dto.workflow_id == str(workflow.id)
        assert dto.status == "active"
        assert dto.starts_at == self.starts_at
        assert dto.next_run_at is None
        schedule = HogFlowSchedule.objects.get(id=dto.id)
        assert schedule.rrule == DAILY_ONCE
        assert schedule.timezone == "UTC"

    def test_create_workflow_schedule_rejects_an_archived_workflow(self) -> None:
        workflow = HogFlow.objects.create(
            team=self.team, created_by=self.user, name="Old loop", status=HogFlow.State.ARCHIVED
        )

        with self.assertRaises(WorkflowArchived):
            create_workflow_schedule(
                team_id=self.team.id,
                user_id=self.user.id,
                workflow_id=workflow.id,
                rrule=DAILY_ONCE,
                starts_at=self.starts_at,
            )

        assert not HogFlowSchedule.objects.filter(hog_flow=workflow).exists()

    def test_update_workflow_schedule_moves_starts_at_and_clears_next_run_at(self) -> None:
        workflow = self._create_loop()
        schedule_id = self._create_schedule(workflow)
        HogFlowSchedule.objects.filter(id=schedule_id).update(next_run_at=self.starts_at)
        new_start = self.starts_at + timedelta(days=2)

        dto = update_workflow_schedule(
            team_id=self.team.id,
            user_id=self.user.id,
            workflow_id=workflow.id,
            schedule_id=schedule_id,
            starts_at=new_start,
        )

        assert dto.id == str(schedule_id)
        assert dto.starts_at == new_start
        assert dto.next_run_at is None
        schedule = HogFlowSchedule.objects.get(id=schedule_id)
        assert schedule.starts_at == new_start
        assert schedule.rrule == DAILY_ONCE

    def test_update_workflow_schedule_only_reaches_the_workflow_own_schedules(self) -> None:
        workflow = self._create_loop()
        other_workflow = self._create_loop(name="Other loop")
        schedule_id = self._create_schedule(workflow)

        with self.assertRaises(WorkflowNotFound):
            update_workflow_schedule(
                team_id=self.team.id,
                user_id=self.user.id,
                workflow_id=other_workflow.id,
                schedule_id=schedule_id,
                starts_at=self.starts_at + timedelta(days=2),
            )

        assert HogFlowSchedule.objects.get(id=schedule_id).starts_at == self.starts_at

    def test_archive_workflow_archives_once(self) -> None:
        workflow = self._create_loop()

        archive_workflow(team_id=self.team.id, user_id=self.user.id, workflow_id=workflow.id)

        workflow.refresh_from_db()
        assert workflow.status == "archived"
        archived_at = workflow.updated_at

        archive_workflow(team_id=self.team.id, user_id=self.user.id, workflow_id=workflow.id)

        workflow.refresh_from_db()
        assert workflow.status == "archived"
        assert workflow.updated_at == archived_at

    @parameterized.expand(
        ["create_workflow", "archive_workflow", "create_workflow_schedule", "update_workflow_schedule"]
    )
    def test_a_viewer_is_denied(self, function_name: str) -> None:
        workflow = self._create_loop()
        schedule_id = self._create_schedule(workflow)
        viewer = self._create_user("viewer@example.com")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=None,
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        calls = {
            "create_workflow": lambda: create_workflow(team_id=self.team.id, user_id=viewer.id, data=_loop_payload()),
            "archive_workflow": lambda: archive_workflow(
                team_id=self.team.id, user_id=viewer.id, workflow_id=workflow.id
            ),
            "create_workflow_schedule": lambda: create_workflow_schedule(
                team_id=self.team.id,
                user_id=viewer.id,
                workflow_id=workflow.id,
                rrule=DAILY_ONCE,
                starts_at=self.starts_at,
            ),
            "update_workflow_schedule": lambda: update_workflow_schedule(
                team_id=self.team.id,
                user_id=viewer.id,
                workflow_id=workflow.id,
                schedule_id=schedule_id,
                starts_at=self.starts_at + timedelta(days=2),
            ),
        }

        with self.assertRaises(WorkflowAccessDenied):
            calls[function_name]()

        workflow.refresh_from_db()
        assert workflow.status == "active"
        assert HogFlow.objects.filter(team=self.team).count() == 1
        assert HogFlowSchedule.objects.get(id=schedule_id).starts_at == self.starts_at
