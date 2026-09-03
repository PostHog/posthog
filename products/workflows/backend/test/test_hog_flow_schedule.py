from datetime import UTC, datetime, timedelta

import unittest.mock
from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status

from products.workflows.backend.api.hog_flow import (
    HOG_FLOW_RUN_IDEMPOTENCY_IN_PROGRESS,
    _hog_flow_run_idempotency_cache_key,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
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

    def test_workflow_get_includes_nested_schedules(self):
        workflow = self._create_batch_workflow()
        self.client.post(self._schedules_url(workflow["id"]), SCHEDULE_DATA)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "schedules" in data
        assert len(data["schedules"]) == 1
        assert data["schedules"][0]["rrule"] == SCHEDULE_DATA["rrule"]
        assert data["schedules"][0]["status"] == "active"

    def test_workflow_get_includes_empty_schedules_when_none(self):
        workflow = self._create_batch_workflow()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["schedules"] == []

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
@unittest.mock.patch("products.workflows.backend.api.hog_flow.create_hog_flow_scheduled_invocation")
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


@unittest.mock.patch("products.workflows.backend.api.hog_flow.create_hog_flow_scheduled_invocation")
class TestHogFlowRun(APIBaseTest):
    def _create_workflow(self, workflow_status="active", trigger_type="schedule", variables=None):
        return HogFlow.objects.create(
            team=self.team,
            name="Test Run Workflow",
            status=workflow_status,
            trigger={"type": trigger_type},
            actions=[],
            variables=variables or [],
        )

    def _run_url(self, workflow_id):
        return f"/api/projects/{self.team.id}/hog_flows/{workflow_id}/run/"

    def _mock_success(self, mock_invocation, invocation_id="abc-123"):
        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "queued", "invocation_id": invocation_id}
        # Clear a prior side_effect (e.g. from a failure simulated earlier in the same test) —
        # Mock prioritizes side_effect over return_value, so a stale one would keep raising.
        mock_invocation.side_effect = None
        mock_invocation.return_value = mock_response

    def test_run_queues_invocation(self, mock_invocation):
        self._mock_success(mock_invocation)
        workflow = self._create_workflow()

        response = self.client.post(self._run_url(workflow.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "queued", "invocation_id": "abc-123"}
        mock_invocation.assert_called_once_with(team_id=self.team.id, hog_flow_id=str(workflow.id), variables={})

    def test_run_merges_variable_defaults_and_overrides(self, mock_invocation):
        # Guards the same variable-resolution contract the scheduler applies in
        # internal_process_due_schedules: run-now must not silently drop a workflow's default
        # variables just because the caller only wants to override one of them.
        self._mock_success(mock_invocation)
        workflow = self._create_workflow(
            variables=[{"key": "greeting", "default": "Hello"}, {"key": "name", "default": "World"}]
        )

        response = self.client.post(self._run_url(workflow.id), {"variables": {"name": "Overridden"}}, format="json")

        assert response.status_code == status.HTTP_200_OK
        mock_invocation.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(workflow.id),
            variables={"greeting": "Hello", "name": "Overridden"},
        )

    def test_run_rejects_non_schedule_trigger(self, mock_invocation):
        workflow = self._create_workflow(trigger_type="batch")

        response = self.client.post(self._run_url(workflow.id))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_invocation.assert_not_called()

    def test_run_rejects_inactive_workflow(self, mock_invocation):
        workflow = self._create_workflow(workflow_status="draft")

        response = self.client.post(self._run_url(workflow.id))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_invocation.assert_not_called()

    def test_run_surfaces_cdp_error(self, mock_invocation):
        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 502
        mock_response.text = "bad gateway"
        mock_invocation.return_value = mock_response
        workflow = self._create_workflow()

        response = self.client.post(self._run_url(workflow.id))

        assert response.status_code == 502

    def test_run_accepts_null_variable_override(self, mock_invocation):
        # A null override must reach dispatch as None, not be rejected by the child field —
        # matches the schedule path, which stores raw JSON and applies no such restriction.
        self._mock_success(mock_invocation)
        workflow = self._create_workflow(variables=[{"key": "greeting", "default": "Hello"}])

        response = self.client.post(self._run_url(workflow.id), {"variables": {"greeting": None}}, format="json")

        assert response.status_code == status.HTTP_200_OK
        mock_invocation.assert_called_once_with(
            team_id=self.team.id, hog_flow_id=str(workflow.id), variables={"greeting": None}
        )

    def test_run_rejects_oversized_variable_overrides(self, mock_invocation):
        workflow = self._create_workflow()

        response = self.client.post(self._run_url(workflow.id), {"variables": {"blob": "x" * 6000}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_invocation.assert_not_called()

    def test_run_wraps_connection_error_as_502(self, mock_invocation):
        mock_invocation.side_effect = requests.ConnectionError("boom")
        workflow = self._create_workflow()

        response = self.client.post(self._run_url(workflow.id))

        assert response.status_code == 502

    def test_run_read_timeout_keeps_idempotency_reservation(self, mock_invocation):
        # CDP may already have queued the invocation when the read times out, so a retry
        # under the same key must not dispatch a second one — it should see the reservation
        # still held and get a 409, not a fresh call to CDP.
        mock_invocation.side_effect = requests.exceptions.ReadTimeout("boom")
        workflow = self._create_workflow()

        first = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="timeout-key")
        assert first.status_code == 504

        second = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="timeout-key")
        assert second.status_code == 409
        mock_invocation.assert_called_once()

    def test_run_connection_error_releases_idempotency_reservation(self, mock_invocation):
        # Unlike a read timeout, a connection error means CDP never saw the request, so a
        # retry under the same key must be free to dispatch.
        mock_invocation.side_effect = requests.ConnectionError("boom")
        workflow = self._create_workflow()

        failed = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="conn-error-key")
        assert failed.status_code == 502

        self._mock_success(mock_invocation)
        retried = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="conn-error-key")
        assert retried.status_code == status.HTTP_200_OK
        assert mock_invocation.call_count == 2

    def test_run_with_idempotency_key_dispatches_once(self, mock_invocation):
        self._mock_success(mock_invocation)
        workflow = self._create_workflow()

        first = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-1")
        second = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-1")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert second.json() == first.json()
        mock_invocation.assert_called_once()

    def test_run_with_different_idempotency_keys_dispatches_twice(self, mock_invocation):
        self._mock_success(mock_invocation)
        workflow = self._create_workflow()

        self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-a")
        self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-b")

        assert mock_invocation.call_count == 2

    def test_run_rejects_concurrent_call_with_same_idempotency_key(self, mock_invocation):
        # Simulates a request already in flight: the reservation is in place, but the first
        # call hasn't stored a result yet.
        self._mock_success(mock_invocation)
        workflow = self._create_workflow()

        cache_key = _hog_flow_run_idempotency_cache_key(self.team.id, str(workflow.id), "in-flight-key")
        cache.set(cache_key, HOG_FLOW_RUN_IDEMPOTENCY_IN_PROGRESS, timeout=60)
        self.addCleanup(cache.delete, cache_key)

        response = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="in-flight-key")

        assert response.status_code == 409
        mock_invocation.assert_not_called()

    def test_run_releases_idempotency_reservation_on_cdp_error(self, mock_invocation):
        # A failed first attempt must not permanently block retries under the same key.
        mock_response = unittest.mock.MagicMock()
        mock_response.status_code = 502
        mock_response.text = "bad gateway"
        mock_invocation.return_value = mock_response
        workflow = self._create_workflow()

        failed = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-2")
        assert failed.status_code == 502

        self._mock_success(mock_invocation)
        retried = self.client.post(self._run_url(workflow.id), HTTP_IDEMPOTENCY_KEY="retry-key-2")

        assert retried.status_code == status.HTTP_200_OK
        assert mock_invocation.call_count == 2
