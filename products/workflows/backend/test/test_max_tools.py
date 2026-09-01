from copy import deepcopy

import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async

from posthog.cdp.templates.hog_function_template import sync_template_to_db

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.max_tools import BroadcastAudienceCondition, CreateBroadcastTool
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _email_function_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = "template-email"
    template["name"] = "Email"
    template["inputs_schema"] = [
        {
            "key": "email",
            "type": "native_email",
            "label": "Email",
            "secret": False,
            "hidden": False,
            "required": True,
            "templating": "liquid",
        }
    ]
    return template


class TestCreateBroadcastTool(BaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(_email_function_template())

    def _setup_tool(self) -> CreateBroadcastTool:
        return CreateBroadcastTool(team=self.team, user=self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_creates_draft_broadcast_hog_flow(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="October update",
            audience_conditions=[
                BroadcastAudienceCondition(type="person", key="plan", value=["pro"], operator="exact")
            ],
            email_subject="What's new",
            email_text="Hello!\n\nBig news.",
            from_email="team@example.com",
        )

        assert "broadcast_id" in artifact, content
        assert f"/workflows/broadcasts/{artifact['broadcast_id']}" in content
        assert "sent" in content  # tells the user nothing was sent

        hog_flow = await sync_to_async(HogFlow.objects.get)(id=artifact["broadcast_id"])
        assert hog_flow.kind == "broadcast"
        assert hog_flow.status == "draft"
        assert hog_flow.trigger["type"] == "batch"
        assert hog_flow.trigger["filters"]["properties"][0]["key"] == "plan"
        email_action = next(a for a in hog_flow.actions if a["type"] == "function_email")
        email_value = email_action["config"]["inputs"]["email"]["value"]
        assert email_value["subject"] == "What's new"
        assert "unsubscribe_url" in email_value["html"]  # derived html carries the unsubscribe link
        assert any(a["type"] == "exit" for a in hog_flow.actions)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_event_audience_conditions_with_guidance(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Bad broadcast",
            audience_conditions=[
                BroadcastAudienceCondition(type="event", key="$pageview", value=["1"], operator="exact")
            ],
            email_subject="Nope",
            email_text="Nope",
        )

        assert artifact["error"] == "validation_failed"
        assert "person properties" in content
        assert not await sync_to_async(HogFlow.objects.filter(team=self.team).exists)()
