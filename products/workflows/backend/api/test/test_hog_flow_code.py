from posthog.test.base import APIBaseTest

from posthog.models.team import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _trigger_action() -> dict:
    return {
        "id": "trigger_node",
        "name": "Trigger",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0, "properties": []}],
                "properties": [],
                "filter_test_accounts": False,
            },
        },
    }


def _delay_action(duration: str) -> dict:
    return {"id": "wait_a_day", "name": "Wait a day", "type": "delay", "config": {"delay_duration": duration}}


def _exit_action() -> dict:
    return {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}}


def _content(duration: str) -> dict:
    return {
        "actions": [_trigger_action(), _delay_action(duration), _exit_action()],
        "edges": [
            {"from": "trigger_node", "to": "wait_a_day", "type": "continue"},
            {"from": "wait_a_day", "to": "exit_node", "type": "continue"},
        ],
    }


class TestHogFlowCode(APIBaseTest):
    def _create_flow(self) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Welcome series", "exit_condition": "exit_only_at_end", **_content("1d")},
        )
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _code(self, flow_id: str):
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/code")

    def test_renders_the_live_definition_as_source(self) -> None:
        flow_id = self._create_flow()

        response = self._code(flow_id)

        assert response.status_code == 200, response.json()
        assert response.json() == {
            "language": "typescript",
            "code": (
                "import { delay, onEvent, path, workflow } from '@posthog/workflows'\n"
                "\n"
                "export const welcomeSeries = workflow({\n"
                "    key: 'welcome-series',\n"
                "    name: 'Welcome series',\n"
                "    status: 'draft',\n"
                "    on: onEvent({ event: '$pageview' }),\n"
                "    steps: path(delay('1d', { name: 'Wait a day' })),\n"
                "    exit: { reason: 'Done' },\n"
                "})\n"
            ),
            "warnings": [],
        }

    def test_prefers_the_staged_draft_over_the_live_definition(self) -> None:
        flow_id = self._create_flow()
        activated = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activated.status_code == 200, activated.json()
        staged = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {**_content("2d"), "stage_draft": True}
        )
        assert staged.status_code == 200, staged.json()
        assert HogFlow.objects.get(pk=flow_id).draft is not None

        response = self._code(flow_id)

        assert response.status_code == 200, response.json()
        assert "delay('2d', { name: 'Wait a day' })" in response.json()["code"]
        assert "'1d'" not in response.json()["code"]

    def test_hides_another_teams_workflow(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        flow = HogFlow.objects.create(team=other_team, name="Theirs", **_content("1d"))

        response = self._code(str(flow.id))

        assert response.status_code == 404
