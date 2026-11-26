from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule

_DISPATCH = (
    "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
)


def _trigger(email_contains: str = "@example.com") -> dict:
    return {
        "id": "trigger_node",
        "name": "trigger_1",
        "type": "trigger",
        "config": {
            "type": "batch",
            "filters": {
                "properties": [{"key": "email", "type": "person", "value": email_contains, "operator": "icontains"}]
            },
        },
    }


def _exit() -> dict:
    return {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}


class TestSentBroadcastLock(APIBaseTest):
    def setUp(self):
        super().setUp()
        dispatch = patch(_DISPATCH)
        self.dispatch = dispatch.start()
        self.addCleanup(dispatch.stop)

    def _url(self, flow_id: str, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/hog_flows/{flow_id}{suffix}"

    def _create_broadcast(
        self,
        *,
        runs: tuple[str, ...] = (),
        schedule: str | None = None,
        origin_product: str | None = HogFlowOriginProduct.BROADCASTS,
    ) -> str:
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Launch announcement",
                "actions": [_trigger(), _exit()],
                "edges": [{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        flow_id = created.json()["id"]
        activated = self.client.patch(self._url(flow_id), {"status": "active"}, format="json")
        assert activated.status_code == 200, activated.json()
        flow = HogFlow.objects.get(pk=flow_id)
        flow.origin_product = origin_product
        flow.save(update_fields=["origin_product"])
        for run in runs:
            HogFlowBatchJob.objects.create(team=self.team, hog_flow=flow, status=run, filters={}, variables={})
        if schedule:
            HogFlowSchedule.objects.create(
                team=self.team,
                hog_flow=flow,
                rrule="FREQ=WEEKLY;BYDAY=MO",
                starts_at=datetime(2026, 1, 5, 9, tzinfo=UTC),
                status=schedule,
            )
        return flow_id

    def _audience(self, flow_id: str) -> str:
        trigger = next(action for action in HogFlow.objects.get(pk=flow_id).actions if action["type"] == "trigger")
        return trigger["config"]["filters"]["properties"][0]["value"]

    def _assert_locked(self, response, flow_id: str) -> None:
        assert response.status_code == 400, response.json()
        assert response.json()["code"] == "broadcast_locked", response.json()
        assert self._audience(flow_id) == "@example.com"
        assert HogFlow.objects.get(pk=flow_id).draft is None

    @parameterized.expand(
        [
            ("never_sent", (), None, HogFlowOriginProduct.BROADCASTS, 200),
            ("sent", ("completed",), None, HogFlowOriginProduct.BROADCASTS, 400),
            ("sent_with_errors", ("partially_failed",), None, HogFlowOriginProduct.BROADCASTS, 400),
            ("run_failed", ("failed",), None, HogFlowOriginProduct.BROADCASTS, 400),
            ("sending", ("active",), None, HogFlowOriginProduct.BROADCASTS, 400),
            ("one_time_schedule_fired", ("completed",), "completed", HogFlowOriginProduct.BROADCASTS, 400),
            ("recurring_between_runs", ("completed",), "active", HogFlowOriginProduct.BROADCASTS, 200),
            ("recurring_paused_by_an_audience_edit", ("completed",), "paused", HogFlowOriginProduct.BROADCASTS, 200),
            ("recurring_while_a_run_sends", ("completed", "active"), "active", HogFlowOriginProduct.BROADCASTS, 400),
            ("workflow_that_ran", ("completed",), None, None, 200),
        ]
    )
    def test_an_audience_edit_is_refused_once_the_broadcast_sent(
        self, _name, runs, schedule, origin_product, expected_status
    ):
        flow_id = self._create_broadcast(runs=runs, schedule=schedule, origin_product=origin_product)

        response = self.client.patch(self._url(flow_id), {"actions": [_trigger("@other.com"), _exit()]}, format="json")

        if expected_status == 400:
            self._assert_locked(response, flow_id)
        else:
            assert response.status_code == 200, response.json()
            assert self._audience(flow_id) == "@other.com"

    def test_a_settings_edit_is_refused_once_the_broadcast_sent(self):
        flow_id = self._create_broadcast(runs=("completed",))

        response = self.client.patch(
            self._url(flow_id), {"email_sending_rate_limit": {"count": 10, "period": "minute"}}, format="json"
        )

        self._assert_locked(response, flow_id)
        assert HogFlow.objects.get(pk=flow_id).email_sending_rate_limit is None

    def test_an_agent_cannot_stage_a_graph_edit_on_a_sent_broadcast(self):
        flow_id = self._create_broadcast(runs=("completed",))

        response = self.client.patch(
            self._url(flow_id, "/graph"),
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "trigger_node",
                        "patch": {"config": _trigger("@other.com")["config"]},
                    }
                ]
            },
            format="json",
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        self._assert_locked(response, flow_id)

    @patch("products.workflows.backend.presentation.views.hog_flow.get_hog_flow_in_flight_count")
    def test_a_draft_staged_before_the_send_cannot_be_published_after_it(self, in_flight_count):
        in_flight_count.return_value = MagicMock(status_code=200, json=lambda: {"count": 0})
        flow_id = self._create_broadcast()
        staged = self.client.patch(
            self._url(flow_id), {"actions": [_trigger("@other.com"), _exit()], "stage_draft": True}, format="json"
        )
        assert staged.status_code == 200, staged.json()
        HogFlowBatchJob.objects.create(team=self.team, hog_flow_id=flow_id, status="completed", filters={})
        preview = self.client.post(self._url(flow_id, "/publish"), {"confirm": False}, format="json")
        assert preview.status_code == 200, preview.json()

        response = self.client.post(
            self._url(flow_id, "/publish"),
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert response.json()["code"] == "broadcast_locked", response.json()
        assert self._audience(flow_id) == "@example.com"

    def test_a_sent_broadcast_can_still_be_renamed_stopped_archived_and_restored(self):
        flow_id = self._create_broadcast(runs=("completed",))
        loaded = self.client.get(self._url(flow_id)).json()

        for payload in (
            {"name": "Launch announcement (sent)"},
            # The web editor resends the unchanged content with every save.
            {"status": "draft", "actions": loaded["actions"], "edges": loaded["edges"]},
            {"status": "archived"},
            {"status": "draft"},
        ):
            response = self.client.patch(self._url(flow_id), payload, format="json")
            assert response.status_code == 200, (payload, response.json())

        flow = HogFlow.objects.get(pk=flow_id)
        assert (flow.name, flow.status) == ("Launch announcement (sent)", "draft")

    @parameterized.expand(
        [
            ("never_sent", (), None, 200),
            ("sent", ("completed",), None, 400),
            ("sending", ("active",), None, 400),
            ("recurring_between_runs", ("completed",), "active", 200),
        ]
    )
    def test_a_sent_broadcast_cannot_be_dispatched_again(self, _name, runs, schedule, expected_status):
        flow_id = self._create_broadcast(runs=runs, schedule=schedule)
        self.dispatch.reset_mock()

        response = self.client.post(self._url(flow_id, "/batch_jobs"), {}, format="json")

        assert response.status_code == expected_status, response.json()
        assert HogFlowBatchJob.objects.filter(hog_flow_id=flow_id).count() == len(runs) + (
            1 if expected_status == 200 else 0
        )
        assert self.dispatch.called == (expected_status == 200)
        if expected_status == 400:
            assert response.json()["code"] == "broadcast_locked", response.json()
