from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import ProjectSecretAPIKey, Team
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.plugins.plugin_server_api import WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.message_templates import TRANSACTIONAL_PUSH_API_FLAG
from products.messaging.backend.services.transactional_email import make_transactional
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


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalPushSend(APIBaseTest):
    def setUp(self):
        super().setUp()
        firebase = Integration.objects.create(team=self.team, kind="firebase", integration_id="my-app")
        self.template = MessageTemplate.objects.create(
            team=self.team,
            name="Order shipped",
            type="push",
            content={"push": {"title": "Shipped", "body": "On its way", "channels": [firebase.id]}},
        )
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        self.url = f"/api/projects/{self.team.id}/messaging/send/push/"
        self.body = {"template_id": str(self.template.id), "distinct_id": "user-1", "message_data": {"order": "42"}}

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="push",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    @parameterized.expand(
        [
            ("push_scope", ["transactional_push:write"], "transactional_push"),
            ("workflow_scope", ["hog_flow:write"], "hog_flow"),
        ]
    )
    def test_queues_the_push_for_the_person(self, mock_post, _flag, capture, _name, scopes, authorized_by):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})

        response = self._psak_client(scopes).post(
            self.url, self.body, format="json", headers={"Idempotency-Key": "order-42"}
        )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {"message_id": "invocation-1", "replayed": False}
        url = mock_post.call_args.args[0]
        assert url.endswith(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}/transactional_push")
        assert mock_post.call_args.kwargs["json"] == {
            "distinct_id": "user-1",
            "variables": {"order": "42"},
            "idempotency_key": "order-42",
        }
        token = mock_post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE.verify(token)
        assert (claims["team_id"], claims["hog_flow_id"], claims["kind"]) == (
            self.team.id,
            str(self.hog_flow_id),
            "push",
        )
        properties = capture.call_args.kwargs["properties"]
        assert (properties["outcome"], properties["authorized_by"]) == ("queued", authorized_by)

    @parameterized.expand(
        [
            ("email_send_scope", ["transactional_email:write"]),
            ("read_only_workflow_scope", ["hog_flow:read"]),
        ]
    )
    def test_a_key_without_the_push_scope_cannot_send(self, mock_post, _flag, _capture, _name, scopes):
        response = self._psak_client(scopes).post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    def test_is_hidden_while_the_push_flag_is_off(self, mock_post, flag, _capture):
        flag.side_effect = lambda key, *args, **kwargs: key != TRANSACTIONAL_PUSH_API_FLAG

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("email_template", "template_not_sendable"),
            ("not_transactional", "template_not_transactional"),
            ("workflow_turned_off", "transactional_push_paused"),
        ]
    )
    def test_refuses_a_template_it_cannot_send(self, mock_post, _flag, _capture, case, code):
        template_id = self.template.id
        if case == "email_template":
            template_id = MessageTemplate.objects.create(
                team=self.team, name="Email", type="email", content={"email": {"subject": "Hi", "html": "<p>Hi</p>"}}
            ).id
        elif case == "not_transactional":
            template_id = MessageTemplate.objects.create(
                team=self.team, name="Draft", type="push", content=self.template.content
            ).id
        else:
            HogFlow.objects.filter(id=self.hog_flow_id).update(status="draft")

        response = self.client.post(self.url, {**self.body, "template_id": str(template_id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == code
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("quota_limited", 429, "quota_limited", status.HTTP_429_TOO_MANY_REQUESTS),
            ("in_flight", 409, "idempotency_key_in_flight", status.HTTP_409_CONFLICT),
            ("reused", 422, "idempotency_key_reused", status.HTTP_422_UNPROCESSABLE_ENTITY),
            ("pipeline_error", 500, "error", status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
    )
    def test_reports_a_send_the_pipeline_refuses(
        self, mock_post, _flag, capture, _name, cdp_status, cdp_error, expected_status
    ):
        mock_post.return_value = MagicMock(status_code=cdp_status, json=lambda: {"error": cdp_error})

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == expected_status, response.json()
        assert capture.call_args.kwargs["properties"]["outcome"] in ("rejected", "unavailable")
