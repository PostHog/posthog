import json
import hashlib
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog import rate_limit
from posthog.models import Organization, ProjectSecretAPIKey, Team
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret
from posthog.plugins.plugin_server_api import WORKFLOWS_TRANSACTIONAL_PUSH_JWT_PURPOSE

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.presentation.views.message_templates import (
    TRANSACTIONAL_PUSH_API_FLAG,
    MessageTemplatesViewSet,
    TransactionalEmailTeamBurstThrottle,
)
from products.messaging.backend.services.transactional_email import make_transactional
from products.messaging.backend.services.transactional_email_status import keyed_run_id
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
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

    @parameterized.expand(
        [
            ("email", "push", "This is an email template, not a push template."),
            ("push", "email", "This is a push template, not an email template."),
        ]
    )
    def test_refuses_a_template_of_another_type(self, _flag, template_type, expected_type, message):
        template = MessageTemplate.objects.create(team=self.team, name="Welcome", type=template_type, content={})

        response = self.client.post(
            f"{self.templates_url}{template.id}/make_transactional/", {"expected_type": expected_type}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "template_type_mismatch"
        assert response.json()["detail"] == message
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    @parameterized.expand([("template_send", "template"), ("send_email", "api")])
    def test_an_email_send_route_refuses_a_transactional_push_template(self, _flag, _name, route):
        template = self._template()
        self._make_transactional(template)
        url, body = (
            (f"{self.templates_url}{template.id}/send/", {})
            if route == "template"
            else (f"/api/projects/{self.team.id}/messaging/send/email/", {"template_id": str(template.id)})
        )

        with patch("posthog.plugins.plugin_server_api.internal_requests.post") as cdp_post:
            response = self.client.post(
                url, {**body, "to": "user@example.com", "identifiers": {"distinct_id": "user-1"}}, format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "template_not_sendable"
        cdp_post.assert_not_called()

    def test_the_project_tree_links_a_push_to_its_own_page(self, _flag):
        template = self._template()

        unfiled = MessageTemplate.get_file_system_unfiled(self.team).get(id=template.id)

        with self.assertNumQueries(0):
            assert unfiled.get_file_system_representation().href == f"/transactional/push/{template.id}"

    def _pak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="make sendable", secure_value=hash_key_value(raw_token), scopes=scopes
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    @parameterized.expand(
        [
            ("email_scope", ["transactional_email:write"], False, True),
            ("push_scope", ["transactional_push:write"], True, False),
            ("both_scopes", ["transactional_email:write", "transactional_push:write"], True, True),
            ("workflow_scope", ["hog_flow:write"], True, True),
            ("workflow_read_scope", ["hog_flow:read"], False, False),
        ]
    )
    def test_each_kind_of_template_needs_its_own_send_scope_to_become_sendable(
        self, _flag, _name, scopes, converts_push, converts_email
    ):
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        email = MessageTemplate.objects.create(
            team=self.team, name="Reset", type="email", content={"email": {"subject": "Hi", "html": "<p>Hi</p>"}}
        )
        client = self._pak_client(scopes)

        for template, converts in ((self._template(), converts_push), (email, converts_email)):
            response = client.post(f"{self.templates_url}{template.id}/make_transactional/", {}, format="json")

            expected = status.HTTP_200_OK if converts else status.HTTP_403_FORBIDDEN
            assert response.status_code == expected, (template.type, response.json())
            template.refresh_from_db()
            assert (template.transactional_hog_flow_id is not None) is converts

    def test_the_email_scope_cannot_reach_a_push_that_is_already_sendable(self, _flag):
        template = self._template()
        linked = self._make_transactional(template).json()["transactional_hog_flow_id"]

        response = self._pak_client(["transactional_email:write"]).post(
            f"{self.templates_url}{template.id}/make_transactional/", {}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        template.refresh_from_db()
        assert str(template.transactional_hog_flow_id) == linked

    @parameterized.expand(
        [
            (
                "email_turned_push_after_its_scope_check",
                "email",
                False,
                "_require_send_scope",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "email_turned_push_before_its_scope_check",
                "email",
                False,
                "dangerously_get_required_scopes",
                status.HTTP_403_FORBIDDEN,
            ),
            ("deleted_push_restored", "push", True, "dangerously_get_required_scopes", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_a_template_that_changes_after_a_scope_check_is_not_made_sendable(
        self, _flag, _name, template_type, deleted, check_name, expected
    ):
        template = self._template(deleted=deleted)
        MessageTemplate.objects.filter(id=template.id).update(type=template_type)
        check = getattr(MessageTemplatesViewSet, check_name)

        def check_then_change(view: Any, *args: Any) -> Any:
            result = check(view, *args)
            MessageTemplate.objects.filter(id=template.id).update(type="push", deleted=False)
            return result

        with patch.object(MessageTemplatesViewSet, check_name, check_then_change):
            response = self._pak_client(["transactional_email:write"]).post(
                f"{self.templates_url}{template.id}/make_transactional/", {}, format="json"
            )

        assert response.status_code == expected, response.json()
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    @parameterized.expand(
        [
            ("email_scope", ["transactional_email:write"]),
            ("push_scope", ["transactional_push:write"]),
            ("both_scopes", ["transactional_email:write", "transactional_push:write"]),
            ("workflow_read_scope", ["hog_flow:read"]),
        ]
    )
    def test_another_organizations_key_cannot_tell_templates_apart(self, _flag, _name, scopes):
        other_team = Organization.objects.bootstrap(None)[2]
        push = MessageTemplate.objects.create(team=other_team, name="Push", type="push", content={"push": self._push()})
        email = MessageTemplate.objects.create(
            team=other_team, name="Email", type="email", content={"email": {"subject": "Hi", "html": "<p>Hi</p>"}}
        )
        client = self._pak_client(scopes)

        answers = [
            client.post(
                f"/api/projects/{other_team.id}/messaging_templates/{template_id}/make_transactional/",
                {},
                format="json",
            )
            for template_id in (push.id, email.id, uuid4())
        ]

        assert {answer.status_code for answer in answers} == {status.HTTP_403_FORBIDDEN}
        assert len({json.dumps(answer.json()) for answer in answers}) == 1, [answer.json() for answer in answers]

    @parameterized.expand([("email_scope", "transactional_email:write"), ("push_scope", "transactional_push:write")])
    def test_either_send_scope_gets_404_for_an_unknown_template(self, _flag, _name, scope):
        response = self._pak_client([scope]).post(
            f"{self.templates_url}{uuid4()}/make_transactional/", {}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    def test_a_transactional_template_cannot_change_between_email_and_push(self, _flag):
        template = self._template()
        self._make_transactional(template)

        response = self.client.patch(
            f"{self.templates_url}{template.id}/",
            {"type": "email", "content": {"email": {"subject": "Hi", "html": "<p>Hi</p>"}}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        template.refresh_from_db()
        assert template.type == "push"

    def test_an_update_without_type_still_needs_a_push_title(self, _flag):
        template = self._template()

        response = self.client.patch(
            f"{self.templates_url}{template.id}/", {"content": {"push": self._push(title=" ")}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        template.refresh_from_db()
        assert template.content["push"]["title"] == self._push()["title"]

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
        claims = WORKFLOWS_TRANSACTIONAL_PUSH_JWT_PURPOSE.verify(token)
        assert (claims["team_id"], claims["hog_flow_id"], claims["distinct_id_sha256"]) == (
            self.team.id,
            str(self.hog_flow_id),
            hashlib.sha256(b"user-1").hexdigest(),
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
            ("too_large", 413, "Request entity too large", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_reports_a_send_the_pipeline_refuses(
        self, mock_post, _flag, capture, _name, cdp_status, cdp_error, expected_status
    ):
        mock_post.return_value = MagicMock(status_code=cdp_status, json=lambda: {"error": cdp_error})

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == expected_status, response.json()
        assert capture.call_args.kwargs["properties"]["outcome"] in ("rejected", "unavailable")

    def test_sends_nothing_while_the_push_key_is_unset(self, mock_post, _flag, _capture):
        with override_settings(WORKFLOWS_TRANSACTIONAL_PUSH_JWT_SECRETS=[]):
            response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.json()
        mock_post.assert_not_called()


def _cdp_answer(cdp_status: int, body: dict[str, Any]) -> MagicMock:
    return MagicMock(status_code=cdp_status, json=lambda: body)


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalPushBatchSend(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
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
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="push",
            secure_value=hash_key_value(raw_token),
            scopes=["transactional_push:write"],
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        self.psak = APIClient()
        self.psak.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        self.url = f"/api/projects/{self.team.id}/messaging/send/push_batch/"

    def _id(self, key: str) -> str:
        return str(keyed_run_id(self.team.id, "transactional-push", key))

    def _recipients(self, count: int) -> list[dict[str, Any]]:
        return [{"distinct_id": f"user-{index}", "idempotency_key": f"key-{index}"} for index in range(count)]

    def _batch(self, recipients: list[dict[str, Any]], **fields: Any) -> Any:
        body = {"template_id": str(self.template.id), "recipients": recipients, **fields}
        return self.psak.post(self.url, body, format="json")

    def _answer_by_key(self, answers: dict[str, MagicMock]) -> Any:
        def answer(url: str, json: dict[str, Any], **kwargs: Any) -> MagicMock:
            return answers.get(json["idempotency_key"]) or _cdp_answer(
                202, {"invocation_id": self._id(json["idempotency_key"])}
            )

        return answer

    def test_each_recipient_is_sent_on_its_own_and_fails_only_its_own_result(self, mock_post, _flag, capture):
        mock_post.side_effect = self._answer_by_key(
            {
                "key-1": _cdp_answer(422, {"error": "idempotency_key_reused"}),
                "key-2": _cdp_answer(500, {"error": "internal_error"}),
                "key-3": _cdp_answer(202, {"invocation_id": self._id("key-3"), "replayed": True}),
                "key-4": _cdp_answer(202, {}),
            }
        )
        recipients = self._recipients(5)
        recipients[0]["message_data"] = {"order": "own"}

        response = self._batch(recipients, message_data={"order": "shared", "eta": "today"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "results": [
                {"message_id": self._id("key-0"), "status": "queued", "replayed": False},
                {
                    "message_id": self._id("key-1"),
                    "error": {
                        "code": "idempotency_key_reused",
                        "detail": response.json()["results"][1]["error"]["detail"],
                        "status": 422,
                        "retryable": False,
                    },
                },
                {
                    "message_id": self._id("key-2"),
                    "error": {
                        "code": "delivery_unavailable",
                        "detail": response.json()["results"][2]["error"]["detail"],
                        "status": 503,
                        "retryable": True,
                    },
                },
                {"message_id": self._id("key-3"), "status": "queued", "replayed": True},
                {
                    "message_id": self._id("key-4"),
                    "error": response.json()["results"][2]["error"],
                },
            ]
        }
        payloads = sorted((call.kwargs["json"] for call in mock_post.call_args_list), key=lambda p: p["distinct_id"])
        assert payloads[0] == {
            "distinct_id": "user-0",
            "variables": {"order": "own", "eta": "today"},
            "idempotency_key": "key-0",
        }
        assert payloads[1]["variables"] == {"order": "shared", "eta": "today"}
        tokens = [
            WORKFLOWS_TRANSACTIONAL_PUSH_JWT_PURPOSE.verify(
                call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            )
            for call in mock_post.call_args_list
        ]
        assert {token["distinct_id_sha256"] for token in tokens} == {
            hashlib.sha256(p["distinct_id"].encode()).hexdigest() for p in payloads
        }
        assert len({token["jti"] for token in tokens}) == len(tokens)
        assert all(
            call.args[0].endswith(f"/hog_flows/{self.hog_flow_id}/transactional_push")
            for call in mock_post.call_args_list
        )
        outcomes = sorted(call.kwargs["properties"]["outcome"] for call in capture.call_args_list)
        assert outcomes == ["queued", "rejected", "replayed", "unavailable", "unavailable"]

    @parameterized.expand(
        [
            ("quota", 429, {"error": "quota_limited"}, status.HTTP_429_TOO_MANY_REQUESTS, "quota_limited"),
            ("pipeline_down", 500, {"error": "internal_error"}, status.HTTP_503_SERVICE_UNAVAILABLE, None),
        ]
    )
    def test_a_refusal_every_recipient_gets_refuses_the_whole_batch(
        self, mock_post, _flag, _capture, _name, cdp_status, body, expected_status, code
    ):
        mock_post.return_value = _cdp_answer(cdp_status, body)

        response = self._batch(self._recipients(3))

        assert response.status_code == expected_status, response.json()
        assert "results" not in response.json()
        if code:
            assert response.json()["code"] == code

    def test_a_batch_stops_sending_at_its_deadline(self, mock_post, _flag, _capture):
        clock = [0.0]

        def stall(url: str, json: dict[str, Any], **kwargs: Any) -> MagicMock:
            clock[0] += 31
            return _cdp_answer(202, {"invocation_id": self._id(json["idempotency_key"])})

        mock_post.side_effect = stall
        module = "products.messaging.backend.services.transactional_push"

        with (
            patch(f"{module}.PUSH_BATCH_PARALLEL_REQUESTS", 1),
            patch(f"{module}.time.monotonic", side_effect=lambda: clock[0]),
        ):
            response = self._batch(self._recipients(3))

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert [result.get("status") or result["error"]["code"] for result in results] == [
            "queued",
            "delivery_unavailable",
            "delivery_unavailable",
        ]
        assert results[1]["error"]["retryable"] is True
        assert mock_post.call_count == 1

    def test_a_turned_off_workflow_refuses_the_batch_without_sending(self, mock_post, _flag, _capture):
        HogFlow.objects.filter(id=self.hog_flow_id).update(status="draft")

        response = self._batch(self._recipients(2))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "transactional_push_paused"
        mock_post.assert_not_called()

    @parameterized.expand([("at_the_cap", 0, True), ("one_byte_over", 1, False)])
    def test_shared_message_data_is_capped_like_the_email_batch(self, mock_post, _flag, _capture, _name, extra, sent):
        mock_post.side_effect = self._answer_by_key({})
        # Two bytes per "é", so a count of characters would let more through.
        shared = {"note": "é" * 100}
        shared["note"] += "x" * (256 * 1024 - len(json.dumps(shared, ensure_ascii=False).encode()) + extra)

        response = self._batch(self._recipients(2), message_data=shared)

        if sent:
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert mock_post.call_count == 2
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["code"] == "content_too_large"
            assert "256 KiB" in response.json()["detail"]
            mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("at_the_cap", 0, {}, True),
            ("one_byte_over", 1, {}, False),
            # Counted once for the batch and once for the recipient, as the email batch does.
            ("at_the_cap_overriding_a_shared_key", 0, {"note": "own"}, True),
            ("one_byte_over_overriding_a_shared_key", 1, {"note": "own"}, False),
        ]
    )
    def test_all_copies_of_a_batch_are_capped_like_the_email_batch(
        self, mock_post, _flag, _capture, _name, extra, own, sent
    ):
        mock_post.side_effect = self._answer_by_key({})

        def size(value: dict[str, Any]) -> int:
            return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

        # Four bytes each, so a count of characters would let more through.
        shared = {"note": "😀" * 40_000}
        recipients = self._recipients(100)
        first = {**own, "pad": ""}
        rest = 16 * 1024 * 1024 - 100 * size(shared) - 99 * size({}) - size(first)
        assert rest >= 0
        recipients[0]["message_data"] = {**first, "pad": "x" * (rest + extra)}

        response = self._batch(recipients, message_data=shared)

        if sent:
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert mock_post.call_count == 100
        else:
            assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, response.json()
            assert response.json()["code"] == "content_too_large"
            mock_post.assert_not_called()

    @parameterized.expand(
        [
            (
                "duplicate_key",
                [{"distinct_id": "a", "idempotency_key": "k"}, {"distinct_id": "b", "idempotency_key": "k"}],
            ),
            ("missing_key", [{"distinct_id": "a"}]),
            ("too_many", [{"distinct_id": f"u{i}", "idempotency_key": f"k{i}"} for i in range(101)]),
            ("empty", []),
        ]
    )
    def test_refuses_a_batch_with_invalid_recipients(self, mock_post, _flag, _capture, _name, recipients):
        response = self._batch(recipients)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        mock_post.assert_not_called()

    def test_a_batch_spends_one_send_per_recipient(self, mock_post, _flag, _capture):
        mock_post.side_effect = self._answer_by_key({})
        rate_limit.is_rate_limit_enabled.cache_clear()
        rate_limit.get_team_allow_list.cache_clear()
        self.addCleanup(rate_limit.is_rate_limit_enabled.cache_clear)
        self.addCleanup(rate_limit.get_team_allow_list.cache_clear)

        with (
            override_instance_config("RATE_LIMIT_ENABLED", True),
            patch.object(TransactionalEmailTeamBurstThrottle, "rate", "5/minute"),
        ):
            spent = self._batch(self._recipients(3))
            refused = self._batch(self._recipients(3))

        assert spent.status_code == status.HTTP_200_OK, spent.json()
        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_post.call_count == 3
