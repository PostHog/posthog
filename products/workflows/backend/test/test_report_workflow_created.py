import pytest
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.models.user import User

from products.workflows.backend.tasks.hog_flows import report_workflow_created

SCOPED_CAPTURE = "products.workflows.backend.tasks.hog_flows.ph_scoped_capture"


def captured_events(scoped_capture: MagicMock) -> list[dict]:
    capture = scoped_capture.return_value.__enter__.return_value
    return [call.kwargs for call in capture.call_args_list]


class TestReportWorkflowCreated(TestCase):
    def setUp(self):
        super().setUp()
        self.org, self.team, _ = User.objects.bootstrap("Test org", "ben@posthog.com", None)

    @override_settings(CLOUD_DEPLOYMENT="EU")
    @patch(SCOPED_CAPTURE)
    def test_sends_the_event_through_the_scoped_client(self, scoped_capture: MagicMock) -> None:
        report_workflow_created(
            team_id=self.team.id, hog_flow_id="flow-1", origin_product="broadcasts", actions_count=1
        )

        assert scoped_capture.call_args.kwargs == {"event_region": "EU", "raise_on_error": True}
        events = captured_events(scoped_capture)
        assert len(events) == 1
        assert events[0]["event"] == "workflows workflow created"
        assert events[0]["distinct_id"] == str(self.team.uuid)
        assert events[0]["groups"]["project"] == str(self.team.uuid)
        assert events[0]["groups"]["organization"] == str(self.org.id)
        assert events[0]["properties"] == {
            "workflow_id": "flow-1",
            "origin_product": "broadcasts",
            "actions_count": 1,
        }

    @patch("posthog.ph_client.is_cloud", return_value=True)
    @patch("posthog.ph_client.get_client")
    def test_failed_upload_fails_the_task(self, get_client: MagicMock, _is_cloud: MagicMock) -> None:
        def client_whose_upload_fails(region: str, on_error=None, **kwargs) -> MagicMock:
            client = MagicMock(super_properties={})
            if on_error is not None:
                client.shutdown.side_effect = lambda: on_error(RuntimeError("Upload failed"), [])
            return client

        get_client.side_effect = client_whose_upload_fails

        with pytest.raises(RuntimeError, match="Upload failed"):
            report_workflow_created(team_id=self.team.id, hog_flow_id="flow-1", origin_product=None, actions_count=0)
