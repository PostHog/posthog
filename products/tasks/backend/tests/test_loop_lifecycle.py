from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_lifecycle import (
    DISABLED_REASON_OWNER_DEACTIVATED,
    DISABLED_REASON_OWNER_REMOVED,
    pause_loops_for_deactivated_user,
    pause_loops_for_removed_member,
)
from products.tasks.backend.models import Loop, Task, TaskRun

LIFECYCLE_MODULE = "products.tasks.backend.loop_lifecycle"


class TestPauseLoopsForDeactivatedUser(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Owner", password="password")

    def _loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Daily digest",
            "instructions": "Summarize",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "enabled": True,
        }
        defaults.update(overrides)
        return Loop.objects.unscoped().create(**defaults)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    def test_deactivation_pauses_records_reason_and_notifies(self, mock_dispatch, _mock_pause):
        loop = self._loop()

        pause_loops_for_deactivated_user(self.user.id)

        loop.refresh_from_db()
        self.assertFalse(loop.enabled)
        self.assertEqual(loop.disabled_reason, DISABLED_REASON_OWNER_DEACTIVATED)
        reasons = [call.args[2].get("reason") for call in mock_dispatch.call_args_list if len(call.args) >= 3]
        self.assertIn(DISABLED_REASON_OWNER_DEACTIVATED, reasons)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_cancels_and_signals_in_flight_runs(self, mock_signal, _mock_dispatch, _mock_pause):
        # Cancelling the DB row isn't enough: the live sandbox must be told to stop, or it runs to
        # completion under the deactivated owner's revoked credentials. Deactivation must signal each run.
        loop = self._loop()
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_member_removal_pauses_loops_and_cancels_runs_in_that_org_only(
        self, mock_signal, _mock_dispatch, _mock_pause
    ):
        # Offboarding leaves is_active=True, so in-flight runs would otherwise keep minting the former
        # org's credentials. Removal must pause the loop and cancel its run — but only in that org.
        loop = self._loop()
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_loop = self._loop(team=other_team)

        pause_loops_for_removed_member(self.user.id, str(self.organization.id))

        loop.refresh_from_db()
        self.assertFalse(loop.enabled)
        self.assertEqual(loop.disabled_reason, DISABLED_REASON_OWNER_REMOVED)
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)
        other_loop.refresh_from_db()
        self.assertTrue(other_loop.enabled)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_cancels_a_transferred_loops_run_authored_by_the_user(
        self, mock_signal, _mock_dispatch, _mock_pause
    ):
        # The run's credentials come from its task's creator. If the loop was taken over after the
        # run started, it is no longer owned by the original author, so pausing loops by current
        # ownership misses the run — it would keep running under the deactivated author's credentials.
        new_owner = User.objects.create_user(email="new@example.com", first_name="New", password="password")
        loop = self._loop(created_by=new_owner)
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)
