import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

CANCEL_PROXY = "products.workflows.backend.api.hog_flow.cancel_hog_flow_invocations"
CANCEL_BATCH_PROXY = "products.workflows.backend.api.hog_flow.cancel_hog_flow_batch_job"
BATCH_DISPATCH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)


def _cdp_response(marked: int = 1, remaining: int = 0, done: bool = True) -> MagicMock:
    return MagicMock(status_code=200, json=lambda: {"marked": marked, "remaining": remaining, "done": done})


class TestHogFlowCancelInvocations(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])

    def _cancel(self, data: dict):
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/invocations/cancel/",
            data=data,
            format="json",
        )

    def test_cancel_by_ids_proxies_with_team_and_flow_pinned(self):
        invocation_id = str(uuid.uuid4())
        with patch(CANCEL_PROXY, return_value=_cdp_response()) as mock_cancel:
            response = self._cancel({"invocation_ids": [invocation_id]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"marked": 1, "remaining": 0, "done": True}
        mock_cancel.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(self.hog_flow.id),
            payload={"invocation_ids": [invocation_id]},
        )

    def test_cancel_all_repeats_until_done_and_aggregates_marked(self):
        # A very large workflow can't be flagged in one bounded sweep. The endpoint must keep
        # calling while the CDP side reports rows remaining, and aggregate the marked counts.
        with patch(
            CANCEL_PROXY,
            side_effect=[_cdp_response(marked=100, remaining=40, done=False), _cdp_response(marked=40)],
        ) as mock_cancel:
            response = self._cancel({"all": True})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"marked": 140, "remaining": 0, "done": True}
        assert mock_cancel.call_count == 2
        assert mock_cancel.call_args.kwargs["payload"] == {"all": True}

    @parameterized.expand(
        [
            ("no_selector", {}),
            ("both_selectors", {"invocation_ids": [str(uuid.uuid4())], "all": True}),
            # An empty list is not a valid selector: it must 400 at Django, not fall
            # through to the CDP proxy and surface the Node 400 as a 500.
            ("empty_ids", {"invocation_ids": []}),
        ]
    )
    def test_cancel_rejects_ambiguous_selectors(self, _name, data):
        with patch(CANCEL_PROXY) as mock_cancel:
            response = self._cancel(data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        mock_cancel.assert_not_called()

    def test_cancel_reaches_parked_runs_of_a_deleted_flow(self):
        # Workflow deletes are hard deletes, so a flow deleted with runs still parked has no row.
        # The cancel endpoint must still proxy for the URL id instead of 404ing before the sweep.
        flow_id = str(self.hog_flow.id)
        self.hog_flow.delete()

        with patch(CANCEL_PROXY, return_value=_cdp_response()) as mock_cancel:
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/invocations/cancel/",
                data={"all": True},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        mock_cancel.assert_called_once_with(team_id=self.team.id, hog_flow_id=flow_id, payload={"all": True})

    def test_cancel_rejects_a_malformed_flow_id_without_proxying(self):
        with patch(CANCEL_PROXY) as mock_cancel:
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/not-a-uuid/invocations/cancel/",
                data={"all": True},
                format="json",
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_cancel.assert_not_called()

    def test_cancel_surfaces_cdp_failure_without_reporting_success(self):
        with patch(CANCEL_PROXY, return_value=MagicMock(status_code=503, text="cyclotron unavailable")):
            response = self._cancel({"all": True})

        assert response.status_code >= 500


class TestHogFlowCancelBatchJob(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])

    def _create_batch_job(self, job_status: str) -> HogFlowBatchJob:
        # Creating a batch job dispatches to the CDP worker via post_save; stub it out.
        with patch(BATCH_DISPATCH):
            return HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, status=job_status)

    def _cancel(self, batch_job_id):
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/batch_jobs/{batch_job_id}/cancel/"
        )

    def test_cancel_active_batch_job_flags_run_and_marks_cancelled(self):
        batch_job = self._create_batch_job("active")

        with patch(CANCEL_BATCH_PROXY, return_value=_cdp_response(marked=5)) as mock_cancel:
            response = self._cancel(batch_job.id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"status": "cancelled", "marked": 5, "remaining": 0, "done": True}
        mock_cancel.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(self.hog_flow.id),
            batch_job_id=str(batch_job.id),
        )
        batch_job.refresh_from_db()
        assert batch_job.status == "cancelled"

    @parameterized.expand([("completed",), ("cancelled",), ("failed",)])
    def test_cancel_terminal_batch_job_is_a_no_op(self, terminal_status):
        batch_job = self._create_batch_job(terminal_status)

        with patch(CANCEL_BATCH_PROXY) as mock_cancel:
            response = self._cancel(batch_job.id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == terminal_status
        mock_cancel.assert_not_called()

    def test_cancel_does_not_clobber_a_run_that_completed_mid_request(self):
        # The resolver's terminal write can land between the flag sweep and the status
        # flip; the genuine completion must win over the cancel.
        batch_job = self._create_batch_job("active")

        def complete_job_then_respond(**kwargs):
            HogFlowBatchJob.objects.filter(id=batch_job.id).update(status="completed")
            return _cdp_response(marked=0)

        with patch(CANCEL_BATCH_PROXY, side_effect=complete_job_then_respond):
            response = self._cancel(batch_job.id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "completed"
        batch_job.refresh_from_db()
        assert batch_job.status == "completed"

    def test_cancel_not_done_after_sweep_cap_leaves_status_untouched(self):
        # A pathological backlog can outlast the bounded sweeps. The run must not read
        # as terminally cancelled while unflagged runs are still in flight.
        batch_job = self._create_batch_job("active")

        with patch(CANCEL_BATCH_PROXY, return_value=_cdp_response(marked=10, remaining=5, done=False)) as mock_cancel:
            response = self._cancel(batch_job.id)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"status": "active", "marked": 50, "remaining": 5, "done": False}
        assert mock_cancel.call_count == 5
        batch_job.refresh_from_db()
        assert batch_job.status == "active"

    @parameterized.expand(
        [
            ("unknown_id", str(uuid.uuid4())),
            # A non-UUID id raises DjangoValidationError during query prep, before any
            # SQL - it must surface as 404, not a 500 reported to error tracking.
            ("malformed_id", "not-a-uuid"),
        ]
    )
    def test_cancel_missing_batch_job_404s(self, _name, batch_job_id):
        with patch(CANCEL_BATCH_PROXY) as mock_cancel:
            response = self._cancel(batch_job_id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_cancel.assert_not_called()

    def test_cancel_batch_job_of_another_flow_404s(self):
        other_flow = HogFlow.objects.create(team=self.team, name="Other", trigger={}, actions=[], edges=[])
        with patch(BATCH_DISPATCH):
            other_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=other_flow, status="active")

        with patch(CANCEL_BATCH_PROXY) as mock_cancel:
            response = self._cancel(other_job.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_cancel.assert_not_called()
