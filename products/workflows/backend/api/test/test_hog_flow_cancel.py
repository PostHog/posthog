import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

CANCEL_PROXY = "products.workflows.backend.api.hog_flow.cancel_hog_flow_invocations"


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
