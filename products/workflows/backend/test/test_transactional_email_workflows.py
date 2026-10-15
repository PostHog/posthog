from copy import deepcopy
from uuid import uuid4

from posthog.test.base import BaseTest

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.facade.contracts import TransactionalEmailContent
from products.workflows.backend.facade.transactional_emails import (
    create_transactional_email_workflow,
    update_transactional_email_workflow,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer


def _content(subject: str = "Reset your password") -> TransactionalEmailContent:
    return TransactionalEmailContent(
        message_template_id=uuid4(),
        name="Password reset",
        subject=subject,
        preheader="",
        html="<a href='{{ variables.link }}'>Reset</a>",
        text="Reset: {{ variables.link }}",
        from_integration_id=1,
        message_category_id=None,
    )


class TestTransactionalEmailWorkflows(BaseTest):
    def setUp(self):
        super().setUp()
        template = dict(MOCK_NODE_TEMPLATES[0])
        template["id"] = "template-email"
        template["inputs_schema"] = [
            {"key": "email", "type": "native_email", "label": "Email", "required": True, "templating": "liquid"}
        ]
        sync_template_to_db(template)

    def test_a_content_change_writes_a_new_version_and_keeps_the_email_live(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())

        update_transactional_email_workflow(
            team_id=self.team.id, user_id=self.user.id, hog_flow_id=flow_id, content=_content(subject="New subject")
        )

        flow = HogFlow.objects.get(id=flow_id)
        assert flow.status == HogFlow.State.ACTIVE
        assert flow.origin_product == "transactional_emails"
        assert flow.version == 2
        assert flow.actions[1]["config"]["inputs"]["email"]["value"]["subject"] == "New subject"
        versions = (
            HogFlowRevision.objects.for_team(self.team.id)
            .filter(hog_flow=flow)
            .order_by("version")
            .values_list("version", flat=True)
        )
        assert list(versions) == [1, 2]

    def test_the_stored_workflow_passes_the_workflows_api_validation(self):
        flow = HogFlow.objects.get(
            id=create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())
        )

        serializer = HogFlowSerializer(
            data=deepcopy({"name": flow.name, "status": "active", "actions": flow.actions, "edges": flow.edges}),
            context={"team_id": self.team.id, "get_team": lambda: self.team, "is_draft": False},
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["trigger"] == flow.trigger == {"type": "api"}
        assert serializer.validated_data["billable_action_types"] == flow.billable_action_types
