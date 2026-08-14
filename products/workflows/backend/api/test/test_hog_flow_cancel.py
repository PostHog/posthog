import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob

CANCEL_PROXY = "products.workflows.backend.api.hog_flow.cancel_hog_flow_invocations"
BATCH_DISPATCH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)


def _cdp_response(marked: int = 1, remaining: int = 0, done: bool = True, ids: list | None = None) -> MagicMock:
    payload: dict = {"marked": marked, "remaining": remaining, "done": done}
    if ids is not None:
        payload["ids"] = ids
    return MagicMock(status_code=200, json=lambda: payload)


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

    def test_cancel_by_ids_proxies_and_returns_outcomes(self):
        invocation_id = str(uuid.uuid4())
        outcomes = [{"id": invocation_id, "outcome": "requested"}]
        with patch(CANCEL_PROXY, return_value=_cdp_response(ids=outcomes)) as mock_cancel:
            response = self._cancel({"invocation_ids": [invocation_id]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"marked": 1, "remaining": 0, "done": True, "ids": outcomes}
        mock_cancel.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(self.hog_flow.id),
            payload={"invocation_ids": [invocation_id]},
        )

    def test_cancel_all_repeats_until_done(self):
        # A very large workflow can't be flagged in one bounded sweep - the endpoint must keep
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


class TestHogFlowCancelBatchJob(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])

    def _create_batch_job(self, job_status: str) -> HogFlowBatchJob:
        with patch(BATCH_DISPATCH):
            return HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, status=job_status)

    def _cancel(self, batch_job: HogFlowBatchJob):
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/batch_jobs/{batch_job.id}/cancel/",
        )

    def test_cancel_active_batch_job_flags_children_and_marks_cancelled(self):
        batch_job = self._create_batch_job("active")

        with patch(CANCEL_PROXY, return_value=_cdp_response(marked=5)) as mock_cancel:
            response = self._cancel(batch_job)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "cancelled"
        mock_cancel.assert_called_once_with(
            team_id=self.team.id,
            hog_flow_id=str(self.hog_flow.id),
            payload={"parent_run_id": str(batch_job.id)},
        )
        batch_job.refresh_from_db()
        assert batch_job.status == "cancelled"

    @parameterized.expand([("completed",), ("cancelled",), ("failed",)])
    def test_cancel_terminal_batch_job_is_a_no_op(self, terminal_status):
        batch_job = self._create_batch_job(terminal_status)

        with patch(CANCEL_PROXY) as mock_cancel:
            response = self._cancel(batch_job)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == terminal_status
        mock_cancel.assert_not_called()

    def test_cancel_does_not_clobber_a_run_that_completed_mid_request(self):
        # The resolver can finish the run between the flag write and the status update; a
        # genuine completion must win over the cancel, mirroring the terminal-absorb rule of
        # the internal status endpoint.
        batch_job = self._create_batch_job("active")

        def complete_job_then_respond(**kwargs):
            HogFlowBatchJob.objects.filter(id=batch_job.id).update(status="completed")
            return _cdp_response(marked=0)

        with patch(CANCEL_PROXY, side_effect=complete_job_then_respond):
            response = self._cancel(batch_job)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "completed"
        batch_job.refresh_from_db()
        assert batch_job.status == "completed"

    def test_cancel_unknown_batch_job_404s(self):
        with patch(CANCEL_PROXY) as mock_cancel:
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}/batch_jobs/{uuid.uuid4()}/cancel/",
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_cancel.assert_not_called()
