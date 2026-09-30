from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.facade.api import workflow_writer
from products.workflows.backend.facade.contracts import WorkflowUpdate
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer


def _trigger_action() -> dict:
    return {
        "id": "trigger_node",
        "name": "trigger_1",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
        },
    }


def _webhook_action(action_id: str, url: str = "https://example.com") -> dict:
    return {
        "id": action_id,
        "name": action_id,
        "type": "function",
        "config": {"template_id": "template-webhook", "inputs": {"url": {"value": url}}},
    }


def _continue(source: str, target: str) -> dict:
    return {"from": source, "to": target, "type": "continue"}


class TestWorkflowWriter(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(MOCK_NODE_TEMPLATES[0])
        self.enterContext(team_scope(self.team.id))
        self.writer = workflow_writer(
            team=self.team, user=self.user, was_impersonated=False, report_usage=lambda *_args: None
        )

    def _validated(self, data: dict[str, Any], instance: HogFlow | None = None) -> HogFlowSerializer:
        serializer = HogFlowSerializer(
            instance,
            data=data,
            context={"team_id": self.team.id, "get_team": lambda: self.team},
        )
        serializer.is_valid(raise_exception=True)
        return serializer

    def _create(self, **fields: Any) -> HogFlow:
        return self.writer.create(self._validated({"name": "Nudge", "actions": [_trigger_action()], **fields}))

    @parameterized.expand([("named", "Nudge", "Nudge"), ("unnamed", "", "HogFlow")])
    def test_create_persists_the_workflow_for_the_acting_user_and_logs_it(
        self, _case: str, name: str, logged_name: str
    ) -> None:
        workflow = self._create(name=name)

        stored = HogFlow.objects.get(pk=workflow.pk)
        assert (stored.team_id, stored.created_by, stored.name) == (self.team.id, self.user, name)
        assert [
            (log.activity, (log.detail or {}).get("name"))
            for log in ActivityLog.objects.filter(item_id=str(workflow.pk))
        ] == [("created", logged_name)]

    @parameterized.expand(
        [
            ("content_change", "https://changed.example.com", 2, [1, 2]),
            ("unchanged_content", "https://example.com", 1, []),
        ]
    )
    def test_update_versions_only_content_changes(
        self, _name: str, url: str, expected_version: int, expected_revisions: list[int]
    ) -> None:
        workflow = self._create(actions=[_trigger_action(), _webhook_action("action_1")])

        previous = self.writer.update(
            workflow,
            self._validated(
                {"name": "Nudge", "actions": [_trigger_action(), _webhook_action("action_1", url)]}, workflow
            ),
            WorkflowUpdate(stage_as_draft=False),
        )

        stored = HogFlow.objects.get(pk=workflow.pk)
        assert previous is not None and previous.version == 1
        assert stored.version == expected_version
        assert (
            list(HogFlowRevision.objects.filter(hog_flow=stored).order_by("version").values_list("version", flat=True))
            == expected_revisions
        )

    def test_publish_puts_the_staged_draft_live_and_redirects_deleted_steps(self) -> None:
        workflow = self._create(
            actions=[_trigger_action(), _webhook_action("action_1"), _webhook_action("action_2")],
            edges=[_continue("trigger_node", "action_1"), _continue("action_1", "action_2")],
        )
        self.writer.update(
            workflow,
            self._validated(
                {
                    "name": "Nudge",
                    "actions": [_trigger_action(), _webhook_action("action_2")],
                    "edges": [_continue("trigger_node", "action_2")],
                },
                workflow,
            ),
            WorkflowUpdate(stage_as_draft=True),
        )

        published = self.writer.publish_draft(
            workflow, lambda locked: self._validated({"name": locked.name, **(locked.draft or {})}, locked)
        )

        stored = HogFlow.objects.get(pk=published.pk)
        assert [action["id"] for action in stored.actions] == ["trigger_node", "action_2"]
        assert stored.action_redirects == {"action_1": "action_2"}
        assert (stored.draft, stored.version) == (None, 2)
        assert ActivityLog.objects.filter(item_id=str(stored.pk), activity="published").exists()
