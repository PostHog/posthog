from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

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
