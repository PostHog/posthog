from datetime import UTC, datetime, timedelta

import unittest.mock
from posthog.test.base import APIBaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}

SCHEDULE_DATA = {
    "rrule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
    "starts_at": "2030-01-01T09:00:00Z",
    "timezone": "UTC",
}


class TestHogFlowScheduleAPI(APIBaseTest):
    def _create_batch_workflow(self, workflow_status="active"):
        payload = {
            "name": "Test Batch Workflow",
            "status": workflow_status,
            "actions": [
                {
                    "id": "trigger_node",
                    "name": "trigger",
                    "type": "trigger",
                    "config": BATCH_TRIGGER,
                }
            ],
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _schedules_url(self, workflow_id):
        return f"/api/projects/{self.team.id}/hog_flows/{workflow_id}/schedules/"

    def _schedule_detail_url(self, workflow_id, schedule_id):
        return f"/api/projects/{self.team.id}/hog_flows/{workflow_id}/schedules/{schedule_id}/"

    def test_create_schedule(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["rrule"] == "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"

    def test_list_schedules(self):
        workflow = self._create_batch_workflow()
        self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        self.client.post(self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "rrule": "FREQ=DAILY;INTERVAL=1"})

        response = self.client.get(self._schedules_url(workflow["id"]))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    def test_update_schedule(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        response = self.client.patch(
            self._schedule_detail_url(workflow["id"], schedule_id),
            {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["rrule"] == "FREQ=MONTHLY;BYMONTHDAY=1"

    def test_update_schedule_resets_next_run_at(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        schedule = HogFlowSchedule.objects.get(id=schedule_id)
        schedule.next_run_at = timezone.now() + timedelta(days=30)
        schedule.save(update_fields=["next_run_at"])

        response = self.client.patch(
            self._schedule_detail_url(workflow["id"], schedule_id),
            {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"},
        )
        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.next_run_at is None

    def test_update_schedule_variables_preserves_next_run_at(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        schedule = HogFlowSchedule.objects.get(id=schedule_id)
        expected_next_run = timezone.now() + timedelta(days=30)
        schedule.next_run_at = expected_next_run
        schedule.save(update_fields=["next_run_at"])

        response = self.client.patch(
            self._schedule_detail_url(workflow["id"], schedule_id),
            {"variables": {"key": "value"}},
        )
        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.next_run_at == expected_next_run

    def test_update_completed_schedule_reactivates(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        schedule = HogFlowSchedule.objects.get(id=schedule_id)
        schedule.status = "completed"
        schedule.save(update_fields=["status"])

        response = self.client.patch(
            self._schedule_detail_url(workflow["id"], schedule_id),
            {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"},
        )
        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.status == "active"

    def test_update_paused_schedule_stays_paused(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        schedule = HogFlowSchedule.objects.get(id=schedule_id)
        schedule.status = "paused"
        schedule.save(update_fields=["status"])

        response = self.client.patch(
            self._schedule_detail_url(workflow["id"], schedule_id),
            {"rrule": "FREQ=MONTHLY;BYMONTHDAY=1"},
        )
        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.status == "paused"
        assert schedule.next_run_at is None

    def test_delete_schedule(self):
        workflow = self._create_batch_workflow()
        create_response = self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        schedule_id = create_response.json()["id"]

        response = self.client.delete(self._schedule_detail_url(workflow["id"], schedule_id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert HogFlowSchedule.objects.filter(id=schedule_id).count() == 0

    def test_delete_nonexistent_schedule_returns_404(self):
        workflow = self._create_batch_workflow()
        response = self.client.delete(self._schedule_detail_url(workflow["id"], "00000000-0000-0000-0000-000000000000"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_multiple_schedules_per_workflow(self):
        workflow = self._create_batch_workflow()
        self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)
        self.client.post(self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "rrule": "FREQ=DAILY;INTERVAL=1"})

        schedules = HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"])
        assert schedules.count() == 2

    def test_rejects_invalid_rrule(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "rrule": "INVALID"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("FREQ=MINUTELY;INTERVAL=1",),
            ("FREQ=SECONDLY;INTERVAL=1",),
        ]
    )
    def test_rejects_too_frequent_schedules(self, rrule_str):
        workflow = self._create_batch_workflow()
        response = self.client.post(self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "rrule": rrule_str})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_accepts_hourly_schedule(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(
            self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "rrule": "FREQ=HOURLY;INTERVAL=1"}
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_rejects_exhausted_schedule(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(
            self._schedules_url(workflow["id"]),
            {**SCHEDULE_DATA, "rrule": "FREQ=DAILY;COUNT=1", "starts_at": "2020-01-01T09:00:00Z"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_schedule_with_variable_overrides(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(
            self._schedules_url(workflow["id"]),
            {**SCHEDULE_DATA, "variables": {"greeting": "Hello", "count": 5}},
        )
        assert response.status_code == status.HTTP_201_CREATED

        schedule = HogFlowSchedule.objects.get(id=response.json()["id"])
        assert schedule.variables == {"greeting": "Hello", "count": 5}

    def test_schedule_with_non_default_timezone(self):
        workflow = self._create_batch_workflow()
        response = self.client.post(self._schedules_url(workflow["id"]), {**SCHEDULE_DATA, "timezone": "US/Eastern"})
        assert response.status_code == status.HTTP_201_CREATED

        schedule = HogFlowSchedule.objects.get(id=response.json()["id"])
        assert schedule.timezone == "US/Eastern"


@override_settings(INTERNAL_API_SECRET="test-secret")
@unittest.mock.patch(
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)
class TestProcessDueSchedules(APIBaseTest):
    INTERNAL_URL = "/api/internal/hog_flows/process_due_schedules"

    def _create_workflow_with_schedule(self, next_run_at=None, rrule="FREQ=HOURLY;INTERVAL=1", starts_at=None):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Workflow",
            status="active",
            trigger=BATCH_TRIGGER,
            actions=[],
            variables=[{"key": "greeting", "default": "Hello"}],
        )
        schedule = HogFlowSchedule.objects.create(
            team=self.team,
            hog_flow=hog_flow,
            rrule=rrule,
            starts_at=starts_at or datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC),
            timezone="UTC",
            status="active",
            next_run_at=next_run_at,
        )
        return hog_flow, schedule

    def _post(self):
        return self.client.post(
            self.INTERNAL_URL, content_type="application/json", headers={"x-internal-api-secret": "test-secret"}
        )

    def test_due_schedule_is_processed_and_next_run_at_advanced(self, mock_dispatch):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200

        data = response.json()
        assert len(data["processed"]) == 1
        assert str(schedule.id) in data["processed"]

        schedule.refresh_from_db()
        assert schedule.next_run_at is not None
        assert schedule.next_run_at > datetime(2020, 1, 1, tzinfo=UTC)

    def test_due_schedule_creates_batch_job(self, mock_dispatch):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 1

        batch_job = HogFlowBatchJob.objects.filter(hog_flow=hog_flow).first()
        assert batch_job is not None
        assert batch_job.status == "queued"
        assert batch_job.variables == {"greeting": "Hello"}
        mock_dispatch.assert_called_once()

    def test_inactive_workflow_clears_next_run_at(self, mock_dispatch):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        hog_flow.status = "draft"
        hog_flow.save()

        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 0

        schedule.refresh_from_db()
        assert schedule.next_run_at is None

    def test_uninitialized_schedule_gets_next_run_at(self, mock_dispatch):
        _, schedule = self._create_workflow_with_schedule(next_run_at=None)
        response = self._post()
        assert response.status_code == 200
        assert str(schedule.id) in response.json()["initialized"]

        schedule.refresh_from_db()
        assert schedule.next_run_at is not None

    def test_exhausted_rrule_marks_schedule_completed(self, mock_dispatch):
        _, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
            starts_at=datetime(2019, 12, 31, tzinfo=UTC),
            rrule="FREQ=DAILY;COUNT=1",
        )
        response = self._post()
        assert response.status_code == 200

        schedule.refresh_from_db()
        assert schedule.status == "completed"
        assert schedule.next_run_at is None

    def test_bad_rrule_appears_in_failed(self, mock_dispatch):
        _, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
            rrule="INVALID_RRULE",
        )
        response = self._post()
        assert response.status_code == 200
        assert str(schedule.id) in response.json()["failed"]
        assert len(response.json()["processed"]) == 0

    def test_no_due_schedules_returns_empty(self, mock_dispatch):
        self._create_workflow_with_schedule(
            next_run_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 0
        assert len(response.json()["initialized"]) == 0
        assert len(response.json()["failed"]) == 0

    def test_schedule_with_variable_overrides_resolves_correctly(self, mock_dispatch):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        schedule.variables = {"greeting": "Overridden", "extra": "value"}
        schedule.save()

        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 1

        batch_job = HogFlowBatchJob.objects.filter(hog_flow=hog_flow).first()
        assert batch_job is not None
        assert batch_job.variables["greeting"] == "Overridden"
        assert batch_job.variables["extra"] == "value"

    def test_multiple_due_schedules_processed_independently(self, mock_dispatch):
        self._create_workflow_with_schedule(next_run_at=datetime(2020, 1, 1, tzinfo=UTC))
        self._create_workflow_with_schedule(next_run_at=datetime(2020, 1, 1, tzinfo=UTC))
        self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
            rrule="INVALID",
        )

        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 2
        assert len(response.json()["failed"]) == 1

    def test_non_batch_trigger_not_reinitialized(self, mock_dispatch):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        hog_flow.trigger = {"type": "event", "filters": {}}
        hog_flow.save()

        # Step 1 clears next_run_at for non-batch workflows
        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 0

        schedule.refresh_from_db()
        assert schedule.next_run_at is None

        # Step 2 should NOT reinitialize it since trigger is not batch
        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["initialized"]) == 0

        schedule.refresh_from_db()
        assert schedule.next_run_at is None


@override_settings(INTERNAL_API_SECRET="test-secret")
@unittest.mock.patch("posthog.api.hog_flow.create_hog_flow_scheduled_invocation")
class TestProcessDueScheduleTriggers(APIBaseTest):
    INTERNAL_URL = "/api/internal/hog_flows/process_due_schedules"

    def _create_workflow_with_schedule(self, next_run_at=None, rrule="FREQ=HOURLY;INTERVAL=1"):
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Schedule Workflow",
            status="active",
            trigger={"type": "schedule"},
            actions=[],
            variables=[{"key": "greeting", "default": "Hello"}],
        )
        schedule = HogFlowSchedule.objects.create(
            team=self.team,
            hog_flow=hog_flow,
            rrule=rrule,
            starts_at=datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC),
            timezone="UTC",
            status="active",
            next_run_at=next_run_at,
        )
        return hog_flow, schedule

    def _post(self):
        return self.client.post(
            self.INTERNAL_URL, content_type="application/json", headers={"x-internal-api-secret": "test-secret"}
        )

    def test_due_schedule_trigger_dispatches_scheduled_invocation(self, mock_invocation):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200
        assert str(schedule.id) in response.json()["processed"]

        mock_invocation.assert_called_once()
        call_kwargs = mock_invocation.call_args.kwargs
        assert call_kwargs["team_id"] == self.team.id
        assert call_kwargs["hog_flow_id"] == str(hog_flow.id)
        assert call_kwargs["variables"] == {"greeting": "Hello"}

    def test_schedule_trigger_advances_next_run_at(self, mock_invocation):
        _, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200

        schedule.refresh_from_db()
        assert schedule.next_run_at is not None
        assert schedule.next_run_at > datetime(2020, 1, 1, tzinfo=UTC)

    def test_schedule_trigger_uses_variable_overrides(self, mock_invocation):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        schedule.variables = {"greeting": "Hi there", "extra": "value"}
        schedule.save()

        response = self._post()
        assert response.status_code == 200

        mock_invocation.assert_called_once()
        variables = mock_invocation.call_args.kwargs["variables"]
        assert variables["greeting"] == "Hi there"
        assert variables["extra"] == "value"

    def test_inactive_schedule_trigger_workflow_clears_next_run_at(self, mock_invocation):
        hog_flow, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        hog_flow.status = "draft"
        hog_flow.save()

        response = self._post()
        assert response.status_code == 200
        assert len(response.json()["processed"]) == 0

        schedule.refresh_from_db()
        assert schedule.next_run_at is None
        mock_invocation.assert_not_called()

    def test_uninitialized_schedule_trigger_gets_next_run_at(self, mock_invocation):
        _, schedule = self._create_workflow_with_schedule(next_run_at=None)
        response = self._post()
        assert response.status_code == 200
        assert str(schedule.id) in response.json()["initialized"]

        schedule.refresh_from_db()
        assert schedule.next_run_at is not None

    def test_cdp_api_error_lands_in_failed(self, mock_invocation):
        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("CDP API returned 500")
        mock_invocation.return_value = mock_response

        _, schedule = self._create_workflow_with_schedule(
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        response = self._post()
        assert response.status_code == 200
        assert str(schedule.id) in response.json()["failed"]
        assert len(response.json()["processed"]) == 0
