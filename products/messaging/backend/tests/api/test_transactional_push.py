from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.integration import Integration

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.message_templates import TRANSACTIONAL_PUSH_API_FLAG
from products.workflows.backend.facade.models import HogFlow


@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
class TestTransactionalPushTemplates(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.firebase = Integration.objects.create(team=self.team, kind="firebase", integration_id="my-app")
        self.templates_url = f"/api/projects/{self.team.id}/messaging_templates/"

    def _push(self, **overrides: Any) -> dict[str, Any]:
        return {
            "title": "Your order {{ variables.order_id }} shipped",
            "body": "Arriving {{ variables.eta }}",
            "channels": [self.firebase.id],
            **overrides,
        }

    def _template(self, push: dict[str, Any] | None = None, **fields: Any) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team, name="Order shipped", type="push", content={"push": push or self._push()}, **fields
        )

    def _make_transactional(self, template: MessageTemplate) -> Any:
        return self.client.post(f"{self.templates_url}{template.id}/make_transactional/", {}, format="json")

    def test_making_a_push_template_transactional_creates_its_workflow_once(self, _flag):
        template = self._template()

        first = self._make_transactional(template)
        second = self._make_transactional(template)

        assert first.status_code == status.HTTP_200_OK, first.json()
        hog_flow_id = first.json()["transactional_hog_flow_id"]
        assert second.json()["transactional_hog_flow_id"] == hog_flow_id
        flow = HogFlow.objects.get(id=hog_flow_id)
        assert (flow.status, flow.origin_product, flow.trigger) == ("active", "transactional_push", {"type": "api"})
        assert flow.actions[1]["config"]["inputs"]["title"]["value"] == "Your order {{ variables.order_id }} shipped"
        listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows?type=transactional_push").json()
        assert [row["id"] for row in listed["results"]] == [hog_flow_id]

    def test_a_push_template_is_made_transactional_only_while_the_push_flag_is_on(self, flag):
        flag.side_effect = lambda key, *args, **kwargs: key != TRANSACTIONAL_PUSH_API_FLAG
        template = self._template()

        response = self._make_transactional(template)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    @parameterized.expand(
        [
            ("no_title", {"title": ""}, "template_not_sendable"),
            ("no_body", {"body": " "}, "template_not_sendable"),
            ("no_channel", {"channels": []}, "template_not_sendable"),
            ("marketing_category", {}, "marketing_template"),
        ]
    )
    def test_rejects_making_a_push_template_transactional_it_cannot_send(self, _flag, name, overrides, code):
        category = None
        if name == "marketing_category":
            category = MessageCategory.objects.create(
                team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
            )
        template = self._template(self._push(**overrides), message_category=category)

        response = self._make_transactional(template)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == code
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    def test_saving_a_transactional_push_template_writes_a_new_workflow_version(self, _flag):
        template = self._template()
        hog_flow_id = self._make_transactional(template).json()["transactional_hog_flow_id"]

        response = self.client.patch(
            f"{self.templates_url}{template.id}/",
            {"content": {"push": self._push(title="Shipped!", link="myapp://orders")}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        flow = HogFlow.objects.get(id=hog_flow_id)
        assert flow.version == 2
        inputs = flow.actions[1]["config"]["inputs"]
        assert (inputs["title"]["value"], inputs["link"]["value"]) == ("Shipped!", "myapp://orders")

    @parameterized.expand(
        [
            ("another_projects_channel", "other_team", "channels"),
            ("an_email_sender_as_channel", "email", "channels"),
            ("push_without_title", "no_title", "title"),
        ]
    )
    def test_refuses_push_content_it_cannot_send(self, _flag, _name, case, field):
        push = self._push()
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other")
            push["channels"] = [Integration.objects.create(team=other_team, kind="firebase", integration_id="x").id]
        elif case == "email":
            push["channels"] = [Integration.objects.create(team=self.team, kind="email", integration_id="a@b.co").id]
        else:
            push["title"] = ""

        response = self.client.post(
            self.templates_url, {"name": "Order shipped", "type": "push", "content": {"push": push}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == f"content__push__{field}"
