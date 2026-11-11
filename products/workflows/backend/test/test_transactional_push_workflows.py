from copy import deepcopy
from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.facade.contracts import (
    TransactionalPushChannelUnavailable,
    TransactionalPushContent,
    TransactionalPushContentInvalid,
)
from products.workflows.backend.facade.transactional_push import (
    create_transactional_push_workflow,
    update_transactional_push_workflow,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer
from products.workflows.backend.services.hog_flow_revisions import restore_revision
from products.workflows.backend.services.hog_flow_writes import publish_confirm_value, publish_draft

PUSH_INPUTS_SCHEMA = [
    {"key": "distinctId", "type": "string", "label": "Distinct ID", "required": True},
    {"key": "channels", "type": "integration_multi", "integration": "firebase,apns", "label": "Channels"},
    {"key": "title", "type": "string", "label": "Title"},
    {"key": "body", "type": "string", "label": "Body", "templating": "liquid"},
    {"key": "image", "type": "string", "label": "Image"},
    {"key": "link", "type": "string", "label": "Link"},
    {"key": "data", "type": "json", "label": "Data"},
]


class TestTransactionalPushWorkflows(BaseTest):
    def setUp(self):
        super().setUp()
        template = dict(MOCK_NODE_TEMPLATES[0])
        template["id"] = "template-native-push"
        template["inputs_schema"] = PUSH_INPUTS_SCHEMA
        sync_template_to_db(template)
        self.firebase = Integration.objects.create(team=self.team, kind="firebase", integration_id="my-app")
        self.apns = Integration.objects.create(team=self.team, kind="apns", integration_id="com.example.app")

    def _content(self, **overrides) -> TransactionalPushContent:
        fields = {
            "message_template_id": uuid4(),
            "name": "Order shipped",
            "title": "Your order {{ variables.order_id }} shipped",
            "body": "Arriving {{ variables.eta }}",
            "channel_ids": (self.firebase.id, self.apns.id),
            "message_category_id": None,
            "link": "myapp://orders/{{ variables.order_id }}",
            "data": {"order_id": "{{ variables.order_id }}"},
            **overrides,
        }
        return TransactionalPushContent(**fields)

    def test_the_stored_workflow_sends_to_the_api_caller_and_passes_the_workflows_api_validation(self):
        flow = HogFlow.objects.get(
            id=create_transactional_push_workflow(team_id=self.team.id, user_id=self.user.id, content=self._content())
        )

        assert flow.status == HogFlow.State.ACTIVE
        assert flow.origin_product == "transactional_push"
        push = flow.actions[1]
        assert push["type"] == "function_push"
        assert push["config"]["message_category_type"] == "transactional"
        inputs = push["config"]["inputs"]
        assert inputs["distinctId"] == {"value": "{{ event.distinct_id }}", "templating": "liquid"}
        assert inputs["channels"] == {"value": [self.firebase.id, self.apns.id]}
        assert inputs["data"]["value"] == {"order_id": "{{ variables.order_id }}"}
        serializer = HogFlowSerializer(
            data=deepcopy({"name": flow.name, "status": "active", "actions": flow.actions, "edges": flow.edges}),
            context={"team_id": self.team.id, "get_team": lambda: self.team, "is_draft": False},
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["trigger"] == flow.trigger == {"type": "api"}
        assert serializer.validated_data["billable_action_types"] == flow.billable_action_types == ["function_push"]

    def test_a_content_change_writes_a_new_version_and_publishing_an_older_one_keeps_the_protection(self):
        flow_id = create_transactional_push_workflow(
            team_id=self.team.id, user_id=self.user.id, content=self._content()
        )
        update_transactional_push_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            hog_flow_id=flow_id,
            content=self._content(title="Shipped!", channel_ids=(self.apns.id,), sensitive=True),
        )

        flow = HogFlow.objects.get(id=flow_id)
        assert flow.version == 2
        assert flow.actions[1]["config"]["inputs"]["title"]["value"] == "Shipped!"
        assert flow.actions[1]["config"]["inputs"]["channels"]["value"] == [self.apns.id]

        with team_scope(self.team.id):
            restore_revision(hog_flow_id=flow_id, version=1, overwrite=False, expected_draft_updated_at=None)
            draft_updated_at = HogFlow.objects.get(id=flow_id).draft_updated_at
            publish_draft(
                team_id=self.team.id,
                user_id=self.user.id,
                hog_flow_id=flow_id,
                previewed_value=publish_confirm_value(hog_flow_id=flow_id, draft_updated_at=draft_updated_at),
                validate=lambda _state, content: content,
            )

        assert HogFlow.objects.get(id=flow_id).actions[1]["config"]["sensitive"] is True

    @parameterized.expand(
        [
            ("no_title", {"title": " "}, TransactionalPushContentInvalid),
            ("no_body", {"body": ""}, TransactionalPushContentInvalid),
            ("no_channel", {"channel_ids": ()}, TransactionalPushContentInvalid),
            ("email_integration", "email", TransactionalPushChannelUnavailable),
            ("another_teams_channel", "other_team", TransactionalPushChannelUnavailable),
        ]
    )
    def test_content_that_cannot_send_is_refused(self, _name, overrides, error):
        if overrides == "email":
            sender = Integration.objects.create(team=self.team, kind="email", integration_id="hi@example.com")
            overrides = {"channel_ids": (sender.id,)}
        elif overrides == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other")
            other = Integration.objects.create(team=other_team, kind="firebase", integration_id="other-app")
            overrides = {"channel_ids": (self.firebase.id, other.id)}

        with self.assertRaises(error):
            create_transactional_push_workflow(
                team_id=self.team.id, user_id=self.user.id, content=self._content(**overrides)
            )

        assert not HogFlow.objects.filter(team_id=self.team.id).exists()
