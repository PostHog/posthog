from typing import Any
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, ProjectSecretAPIKey, User
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.presentation.views.message_templates import MessageTemplatesViewSet
from products.messaging.backend.presentation.views.transactional_email_api import TransactionalEmailBurstThrottle
from products.messaging.backend.services import transactional_email
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
from products.workflows.backend.models import HogFlow, TeamWorkflowsConfig

PASSWORD_RESET_HASH = "v1:973d41bbe3fdca5c52bb951cd4b5fd7159ae630b56c8f3997cbb31afd1ea76fd"


@patch("products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmail(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, self.sender.id)
        self.template = self._template(key="password-reset")
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        self.url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/send/"
        self.send_email_url = f"/api/projects/{self.team.id}/messaging/send/email/"
        self.body = {
            "to": "user@example.com",
            "identifiers": {"distinct_id": "user-1"},
            "message_data": {"link": "https://example.com/reset", "nickname": None},
        }

    def _template(self, content: dict | None = None, key: str | None = None) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content=content
            or {"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
            key=key,
        )

    def _route(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/{path.format(id=self.template.id)}"

    def _send_request(self, addressed_by: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if addressed_by == "url_id":
            return self.url, body
        template = {"key": "password-reset"} if addressed_by == "key" else {"id": str(self.template.id)}
        return self.send_email_url, {**body, "template": template}

    def _workflow(self, hog_flow_id) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _cdp_accepts(self, mock_post: MagicMock, invocation_id: str = "invocation-1") -> None:
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": invocation_id})

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="transactional email",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    @parameterized.expand(
        [
            ("with_distinct_id", "url_id", {"distinct_id": "user-1"}, "user-1"),
            # Without a distinct_id the recipient's address is the person the send is tracked against.
            ("email_only", "url_id", None, "user@example.com"),
            ("by_key", "key", {"distinct_id": "user-1"}, "user-1"),
            ("by_id", "id", None, "user@example.com"),
        ]
    )
    def test_runs_the_templates_workflow_for_the_recipient(
        self, mock_post, _flag, capture, _name, addressed_by, identifiers, expected_distinct_id
    ):
        self._cdp_accepts(mock_post)
        url, body = self._send_request(
            addressed_by,
            {**self.body, "identifiers": identifiers}
            if identifiers
            else {k: v for k, v in self.body.items() if k != "identifiers"},
        )

        response = self._psak_client(["hog_flow:write"]).post(url, body, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        expected_response: dict[str, Any] = {"message_id": "invocation-1", "replayed": False}
        if addressed_by != "url_id":
            expected_response["warnings"] = []
        assert response.json() == expected_response
        assert capture.call_args.kwargs["properties"]["addressed_by"] == addressed_by
        assert mock_post.call_args.args[0].endswith(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}/transactional_email"
        )
        expected_payload: dict[str, Any] = {
            "to": "user@example.com",
            "distinct_id": expected_distinct_id,
            "variables": {"link": "https://example.com/reset", "nickname": None},
        }
        if addressed_by == "key":
            expected_payload["send"] = {"tracking": {"captureEngagement": True}}
        assert mock_post.call_args.kwargs["json"] == expected_payload

    def test_passes_the_idempotency_key_to_the_pipeline_and_reports_a_replay(self, mock_post, _flag, capture):
        mock_post.return_value = MagicMock(
            status_code=202, json=lambda: {"invocation_id": "first-send", "replayed": True}
        )

        response = self.client.post(self.url, self.body, format="json", headers={"Idempotency-Key": "reset:user-1:42"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {"message_id": "first-send", "replayed": True}
        assert mock_post.call_args.kwargs["json"]["idempotency_key"] == "reset:user-1:42"
        assert capture.call_args.kwargs["properties"]["outcome"] == "replayed"
        assert capture.call_args.kwargs["properties"]["has_idempotency_key"] is True

    @parameterized.expand(
        [
            (
                "send_with_write_scope",
                "post",
                "messaging_templates/{id}/send/",
                ["hog_flow:write"],
                status.HTTP_202_ACCEPTED,
            ),
            (
                "send_with_read_scope",
                "post",
                "messaging_templates/{id}/send/",
                ["hog_flow:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "send_email_with_write_scope",
                "post",
                "messaging/send/email/",
                ["hog_flow:write"],
                status.HTTP_202_ACCEPTED,
            ),
            (
                "send_email_with_read_scope",
                "post",
                "messaging/send/email/",
                ["hog_flow:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "retrieve_is_not_a_psak_action",
                "get",
                "messaging_templates/{id}/",
                ["hog_flow:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "make_transactional_is_not_a_psak_action",
                "post",
                "messaging_templates/{id}/make_transactional/",
                ["hog_flow:write"],
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    def test_project_secret_api_key_can_only_send(
        self, mock_post, _flag, _capture, _name, method, path, scopes, expected_status
    ):
        self._cdp_accepts(mock_post)

        response = getattr(self._psak_client(scopes), method)(
            self._route(path),
            {**self.body, "template": {"key": "password-reset"}} if method == "post" else None,
            format="json",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            (
                "not_transactional",
                "url_id",
                "template_not_transactional",
                "The template isn't transactional. Make it transactional to send it.",
            ),
            *[
                (case, addressed_by, code, detail)
                for addressed_by in ("url_id", "key")
                for case, code, detail in [
                    (
                        "workflow_archived",
                        "transactional_email_paused",
                        "The template's transactional email isn't active.",
                    ),
                    (
                        "category_turned_marketing",
                        "marketing_template",
                        "The template is in a marketing category. Only transactional templates can be sent.",
                    ),
                    ("liquid_in_recipient", "invalid_recipient", "The recipient address can't contain { or }."),
                ]
            ],
            *[
                (
                    case,
                    "url_id",
                    "invalid_idempotency_key",
                    "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces.",
                )
                for case in ("idempotency_key_with_spaces", "idempotency_key_too_long")
            ],
        ]
    )
    def test_rejects_a_send_it_cannot_make(
        self, mock_post, _flag, capture, case, addressed_by, expected_code, expected_detail
    ):
        body, headers = dict(self.body), {}
        if case == "workflow_archived":
            archived = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}", {"status": "archived"}
            )
            assert archived.status_code == status.HTTP_200_OK, archived.json()
        elif case == "category_turned_marketing":
            category = MessageCategory.objects.create(
                team=self.team, key="account", name="Account", category_type=MessageCategoryType.TRANSACTIONAL
            )
            MessageTemplate.objects.filter(id=self.template.id).update(message_category=category)
            MessageCategory.objects.filter(id=category.id).update(category_type=MessageCategoryType.MARKETING)
        elif case == "liquid_in_recipient":
            body["to"] = "{{person.properties.email}}@example.com"
        elif case == "idempotency_key_with_spaces":
            headers["Idempotency-Key"] = "reset user 1"
        elif case == "idempotency_key_too_long":
            headers["Idempotency-Key"] = "k" * 256
        url, body = self._send_request(addressed_by, body)
        if case == "not_transactional":
            url = f"/api/projects/{self.team.id}/messaging_templates/{self._template().id}/send/"

        response = self.client.post(url, body, format="json", headers=headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        error = response.json()
        assert (error["type"], error["code"], error["detail"]) == ("invalid_request", expected_code, expected_detail)
        mock_post.assert_not_called()
        reported = capture.call_args.kwargs["properties"]
        assert (reported["outcome"], reported["error_code"]) == ("rejected", expected_code)

    @parameterized.expand(
        [
            ("unknown_key", {"key": "welcome"}, status.HTTP_409_CONFLICT, "template_outdated", "template__key"),
            ("unknown_id", {"id": str(uuid4())}, status.HTTP_404_NOT_FOUND, "template_not_found", "template__id"),
            ("deleted", {"key": "password-reset"}, status.HTTP_409_CONFLICT, "template_outdated", "template__key"),
            (
                "key_and_id",
                {"key": "password-reset", "id": str(uuid4())},
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "template",
            ),
            ("neither_key_nor_id", {}, status.HTTP_400_BAD_REQUEST, "invalid_request", "template"),
            (
                "hash_with_id",
                {"id": str(uuid4()), "hash": f"v1:{'0' * 64}"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "template",
            ),
            (
                "invalid_key",
                {"key": "password reset"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_template_key",
                "template__key",
            ),
            (
                "field_this_server_lacks",
                {"key": "password-reset", "content_hash": f"v1:{'0' * 64}"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_request",
                "template__content_hash",
            ),
            (
                "key_with_trailing_newline",
                {"key": "password-reset\n"},
                status.HTTP_400_BAD_REQUEST,
                "invalid_template_key",
                "template__key",
            ),
        ]
    )
    def test_refuses_a_template_reference_it_cannot_send_with_what_to_fix(
        self, mock_post, _flag, _capture, case, template, expected_status, expected_code, expected_attr
    ):
        if case == "deleted":
            deleted = self.client.patch(self._route("messaging_templates/{id}/"), {"deleted": True}, format="json")
            assert deleted.status_code == status.HTTP_200_OK, deleted.json()

        response = self.client.post(self.send_email_url, {**self.body, "template": template}, format="json")

        assert response.status_code == expected_status, response.json()
        error = response.json()
        assert (error["code"], error["attr"]) == (expected_code, expected_attr)
        assert error["docs_url"] == f"https://posthog.com/docs/workflows/transactional-email-api#{expected_code}"
        assert error["why"] and error["fix"]
        mock_post.assert_not_called()

    @parameterized.expand([("list", [{"to": "user@example.com"}]), ("string", "user@example.com")])
    def test_refuses_a_body_that_is_not_an_object(self, mock_post, _flag, _capture, _name, body):
        response = self.client.post(self.send_email_url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        error = response.json()
        assert (error["code"], error["attr"]) == ("invalid_request", None)
        assert error["detail"].startswith("Invalid data.")
        assert error["fix"] == "Send the body as a JSON object and send again."
        mock_post.assert_not_called()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_both_send_routes_share_one_rate_limit_per_key(self, _rate_limit, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])

        with patch.object(TransactionalEmailBurstThrottle, "rate", "1/minute"):
            by_url_id = psak.post(self.url, self.body, format="json")
            by_key = psak.post(self.send_email_url, {**self.body, "template": {"key": "password-reset"}}, format="json")

        assert by_url_id.status_code == status.HTTP_202_ACCEPTED, by_url_id.json()
        assert by_key.status_code == status.HTTP_429_TOO_MANY_REQUESTS, by_key.json()
        # Clients retry `throttled`, and never `quota_limited`.
        assert by_key.json()["code"] == "throttled"

    @parameterized.expand(
        [
            (f"{name}_{addressed_by}", addressed_by, outcome)
            for addressed_by in ("url_id", "key")
            for name, outcome in [
                ("timeout", requests.ReadTimeout()),
                ("cdp_api_error", MagicMock(status_code=500)),
            ]
        ]
    )
    def test_a_send_the_pipeline_does_not_confirm_is_unavailable(
        self, mock_post, _flag, capture, _name, addressed_by, outcome
    ):
        if isinstance(outcome, Exception):
            mock_post.side_effect = outcome
        else:
            mock_post.return_value = outcome
        url, body = self._send_request(addressed_by, self.body)

        response = self.client.post(url, body, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "delivery_unavailable"
        assert capture.call_args.kwargs["properties"]["outcome"] == "unavailable"

    def test_a_send_that_breaks_after_the_pipeline_answers_is_counted_as_an_error(self, mock_post, _flag, capture):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {})
        self.client.raise_request_exception = False

        response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert capture.call_args.kwargs["properties"]["outcome"] == "error"

    @parameterized.expand(
        [
            ("update", "", {"name": "Reset"}),
            (
                "design",
                "design/",
                {"operations": [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>New</p>"}}}]},
            ),
        ]
    )
    @patch(
        "products.messaging.backend.presentation.views.message_templates.render_design_html",
        return_value="<p>New</p>",
    )
    def test_a_deleted_workflow_unlinks_the_template_until_it_is_made_transactional_again(
        self, _name, suffix, body, _render, mock_post, _flag, _capture
    ):
        design = {
            "body": {
                "id": "body1",
                "rows": [
                    {
                        "id": "row1",
                        "cells": [1],
                        "columns": [
                            {
                                "id": "col1",
                                "contents": [{"id": "txt1", "type": "text", "values": {"text": "<p>Old</p>"}}],
                                "values": {},
                            }
                        ],
                        "values": {},
                    }
                ],
                "values": {},
            }
        }
        MessageTemplate.objects.filter(id=self.template.id).update(
            content={"email": {**self.template.content["email"], "design": design}}
        )
        deleted = self.client.delete(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        template_url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/"

        edited = self.client.patch(f"{template_url}{suffix}", body, format="json")
        remade = self.client.post(f"{template_url}make_transactional/", {}, format="json")

        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert edited.json()["transactional_hog_flow_id"] is None
        assert remade.json()["transactional_hog_flow_id"] not in (None, str(self.hog_flow_id))

    @parameterized.expand(
        [
            *[
                (
                    f"quota_limited_{addressed_by}",
                    addressed_by,
                    429,
                    "quota_limited",
                    {"error": "quota_limited"},
                    "The project is over its email quota.",
                )
                for addressed_by in ("url_id", "key")
            ],
            (
                "idempotency_key_in_flight",
                "url_id",
                409,
                "idempotency_key_in_flight",
                {"error": "idempotency_key_in_flight"},
                "A request with this Idempotency-Key is still being processed. Retry in a few seconds.",
            ),
            (
                "idempotency_key_reused",
                "url_id",
                422,
                "idempotency_key_reused",
                {"error": "idempotency_key_reused"},
                "This Idempotency-Key was already used for a different request. Use a new key for a new email.",
            ),
            *(
                (
                    code,
                    "url_id",
                    400,
                    code,
                    {"error": code, "code": code, "detail": "Skipping send.", "why": f"Why {code}.", "fix": "Fix it."},
                    "Skipping send.",
                )
                for code in (
                    "invalid_recipient",
                    "sender_not_verified",
                    "sending_suspended",
                    "template_paused",
                    "recipient_suppressed",
                )
            ),
        ]
    )
    def test_reports_a_send_the_pipeline_refuses(
        self, mock_post, _flag, capture, _name, addressed_by, status_code, code, cdp_body, detail
    ):
        mock_post.return_value = MagicMock(status_code=status_code, json=lambda: cdp_body)
        url, body = self._send_request(addressed_by, self.body)

        response = self.client.post(url, body, format="json", headers={"Idempotency-Key": "key-1"})

        assert response.status_code == status_code, response.json()
        error = response.json()
        assert (error["code"], error["detail"]) == (code, detail)
        assert error["docs_url"] == f"https://posthog.com/docs/workflows/transactional-email-api#{code}"
        if "why" in cdp_body:
            assert (error["why"], error["fix"]) == (cdp_body["why"], cdp_body["fix"])
        reported = capture.call_args.kwargs["properties"]
        assert (reported["outcome"], reported["error_code"]) == ("rejected", code)

    def _send_body(self, addressed_by: str, **fields: Any) -> dict[str, Any]:
        if addressed_by == "template_key":
            return self._rendered(**fields)
        _url, body = self._send_request(addressed_by, self.body)
        return {**body, **fields}

    def _rendered(self, **fields: Any) -> dict[str, Any]:
        return {
            "to": "user@example.com",
            "identifiers": {"distinct_id": "user-1"},
            "template_key": "welcome",
            "subject": "Welcome, Jane",
            "html": "<p>Hi {{ variables.name }}</p>",
            **fields,
        }

    @parameterized.expand(
        [
            ("new_key", "welcome"),
            ("key_that_names_a_template", "password-reset"),
        ]
    )
    def test_sends_rendered_content_as_is_under_the_keys_workflow(self, mock_post, _flag, capture, _name, key):
        self._cdp_accepts(mock_post)
        templates_before = MessageTemplate.objects.filter(team=self.team).count()
        psak = self._psak_client(["hog_flow:write"])

        first = psak.post(self.send_email_url, self._rendered(template_key=key), format="json")
        second = psak.post(self.send_email_url, self._rendered(template_key=key, subject="Again"), format="json")

        assert first.status_code == status.HTTP_202_ACCEPTED, first.json()
        assert first.json() == {"message_id": "invocation-1", "replayed": False, "warnings": []}
        assert second.status_code == status.HTTP_202_ACCEPTED, second.json()
        first_url, second_url = (call.args[0] for call in mock_post.call_args_list)
        assert first_url == second_url
        hog_flow_id = first_url.split("/hog_flows/")[1].split("/")[0]
        if key == "password-reset":
            assert hog_flow_id == str(self.hog_flow_id)
        else:
            assert TransactionalEmailKey.objects.for_team(self.team.id).get(key=key).hog_flow_id == UUID(hog_flow_id)
            listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows/").json()["results"]
            assert hog_flow_id not in {workflow["id"] for workflow in listed}
        email_step = next(a for a in self._workflow(hog_flow_id)["actions"] if a["type"] == "function_email")
        assert not email_step["config"].get("utm_tags_enabled")
        assert mock_post.call_args_list[0].kwargs["json"] == {
            "to": "user@example.com",
            "distinct_id": "user-1",
            "variables": {},
            "send": {
                "content": {
                    "subject": "Welcome, Jane",
                    "html": "<p>Hi {{ variables.name }}</p>",
                    "text": "Hi {{ variables.name }}",
                },
                "from": {"integrationId": self.sender.id},
                "tracking": {"captureEngagement": True},
            },
        }
        assert MessageTemplate.objects.filter(team=self.team).count() == templates_before
        assert capture.call_args.kwargs["properties"]["addressed_by"] == "template_key"

    @parameterized.expand(
        [
            (
                "rendered_content",
                "template_key",
                {"text": "Hi", "from": "Example <security@example.com>", "reply_to": ["help@example.com"]},
                {
                    "content": {"subject": "Welcome, Jane", "html": "<p>Hi {{ variables.name }}</p>", "text": "Hi"},
                    "from": {"integrationId": "default", "email": "security@example.com", "name": "Example"},
                    "replyTo": ["help@example.com"],
                    "tracking": {"captureEngagement": True},
                },
            ),
            (
                "rendered_content_without_capture",
                "template_key",
                {"capture_engagement": False},
                {
                    "content": {
                        "subject": "Welcome, Jane",
                        "html": "<p>Hi {{ variables.name }}</p>",
                        "text": "Hi {{ variables.name }}",
                    },
                    "from": {"integrationId": "default"},
                    "tracking": {"captureEngagement": False},
                },
            ),
            (
                "rendered_text_only",
                "template_key",
                {"html": "", "text": "Hi"},
                {
                    "content": {"subject": "Welcome, Jane", "text": "Hi"},
                    "from": {"integrationId": "default"},
                    "tracking": {"captureEngagement": True},
                },
            ),
            (
                "template_by_key",
                "key",
                {"from": "hello@example.com", "reply_to": ["help@example.com"]},
                {
                    "from": {"integrationId": "hello", "email": "hello@example.com"},
                    "replyTo": ["help@example.com"],
                    "tracking": {"captureEngagement": True},
                },
            ),
            (
                "template_by_id_with_capture",
                "id",
                {"capture_engagement": True},
                {"tracking": {"captureEngagement": True}},
            ),
            ("template_by_id", "id", {}, None),
        ]
    )
    def test_a_send_carries_what_the_caller_set_over_its_workflow(
        self, mock_post, _flag, _capture, _name, addressed_by, fields, sent
    ):
        self._cdp_accepts(mock_post)
        newer_default = Integration.objects.create(
            team=self.team, kind="email", integration_id="news@example.com", config={"verified": True}
        )
        TeamWorkflowsConfig.objects.filter(team_id=self.team.id).update(default_email_integration_id=newer_default.id)
        sender_ids = {"hello": self.sender.id, "default": newer_default.id}
        body = self._send_body(addressed_by, **fields)

        response = self._psak_client(["hog_flow:write"]).post(self.send_email_url, body, format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        if sent is not None and "from" in sent:
            sent = {**sent, "from": {**sent["from"], "integrationId": sender_ids[sent["from"]["integrationId"]]}}
        assert mock_post.call_args.kwargs["json"].get("send") == sent

    @parameterized.expand(
        [
            ("template_and_key", {"template": {"key": "password-reset"}}, "invalid_request", "template_key"),
            ("no_subject", {"subject": ""}, "invalid_request", "subject"),
            ("no_body", {"html": None}, "invalid_request", "html"),
            ("data_for_rendered_content", {"message_data": {"name": "Jane"}}, "invalid_request", "message_data"),
            ("quoted_recipient", {"to": '"jane"@example.com'}, "invalid_request", "to"),
            ("recipient_without_a_dotted_domain", {"to": "jane@localhost"}, "invalid_request", "to"),
            (
                "recipient_too_long",
                {"to": f"jane@{'a' * 60}.{'b' * 60}.{'c' * 60}.{'d' * 60}.example.com"},
                "invalid_request",
                "to",
            ),
            ("quoted_reply_to", {"reply_to": ['"help,desk"@example.com']}, "invalid_request", "reply_to__0"),
            ("not_an_address", {"from": "Example"}, "invalid_request", "from"),
            ("quoted_local_part", {"from": '"security"@example.com'}, "invalid_request", "from"),
            ("sender_too_long", {"from": f"{'s' * 250}@example.com"}, "invalid_request", "from"),
            ("empty_reply_to", {"reply_to": []}, "invalid_request", "reply_to"),
            ("unverified_domain", {"from": "Example <security@example.org>"}, "sender_not_allowed", "from"),
            ("invalid_key", {"template_key": "welcome email"}, "invalid_template_key", "template_key"),
            ("field_this_server_lacks", {"scheduled_at": "2026-11-01T09:00:00Z"}, "invalid_request", "scheduled_at"),
            (
                "identifier_this_server_lacks",
                {"identifiers": {"distinct_id": "user-1", "email": "jane@example.com"}},
                "invalid_request",
                "identifiers__email",
            ),
        ]
    )
    def test_refuses_a_rendered_send_it_cannot_make_with_what_to_fix(
        self, mock_post, _flag, _capture, _name, fields, expected_code, expected_attr
    ):
        body = {key: value for key, value in self._rendered(**fields).items() if value is not None}

        response = self._psak_client(["hog_flow:write"]).post(self.send_email_url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        error = response.json()
        assert (error["code"], error["attr"]) == (expected_code, expected_attr)
        assert error["why"] and error["fix"]
        if expected_code == "invalid_request":
            # The why explains the field that failed, not what a send needs in general.
            named = {"reply_to__0": "reply_to", "identifiers__email": "identifiers.email"}.get(
                expected_attr, expected_attr
            )
            assert f"`{named}`" in error["why"], error["why"]
        if expected_attr == "to":
            assert error["detail"] == f"to: `{fields['to']}` is not a bare address. Send it as `jane@example.com`."
        mock_post.assert_not_called()

    def test_the_url_id_route_refuses_a_recipient_the_pipeline_would_split(self, mock_post, _flag, _capture):
        response = self.client.post(self.url, {**self.body, "to": '"help,desk"@example.com'}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "to"
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("subject_with_template", {"subject": "Hi"}, "subject"),
            ("from_with_template_id", {"from": "hello@example.com"}, "from"),
        ]
    )
    def test_refuses_code_fields_on_a_template_made_in_posthog(self, mock_post, _flag, _capture, _name, fields, attr):
        body = {**self.body, "template": {"id": str(self.template.id)}, **fields}

        response = self.client.post(self.send_email_url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["code"], response.json()["attr"]) == ("invalid_request", attr)
        mock_post.assert_not_called()

    def test_two_racing_first_sends_of_a_key_make_one_workflow(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])
        winner = psak.post(self.send_email_url, self._rendered(), format="json")
        lookup = transactional_email.known_key
        lookups: list[str] = []

        def misses_the_winner_once(team_id: int, key: str) -> TransactionalEmailKey | None:
            lookups.append(key)
            return None if len(lookups) == 1 else lookup(team_id, key)

        with patch.object(transactional_email, "known_key", side_effect=misses_the_winner_once):
            loser = psak.post(self.send_email_url, self._rendered(), format="json")

        assert (winner.status_code, loser.status_code) == (status.HTTP_202_ACCEPTED, status.HTTP_202_ACCEPTED)
        first_url, second_url = (call.args[0] for call in mock_post.call_args_list)
        assert first_url == second_url
        assert TransactionalEmailKey.objects.for_team(self.team.id).filter(key="welcome").count() == 1
        assert HogFlow.objects.filter(team=self.team, name="welcome").count() == 1

    @parameterized.expand(
        [
            ("send", "messaging_templates/{id}/send/"),
            ("make_transactional", "messaging_templates/{id}/make_transactional/"),
            ("send_email", "messaging/send/email/"),
        ]
    )
    def test_is_hidden_while_the_flag_is_off(self, mock_post, flag, _capture, _name, path):
        flag.return_value = False

        response = self.client.post(
            self._route(path), {**self.body, "template": {"key": "password-reset"}}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_post.assert_not_called()

    def test_making_a_template_transactional_creates_its_workflow_once(self, mock_post, _flag, _capture):
        template = self._template()
        url = f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/"

        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")

        assert first.status_code == status.HTTP_200_OK, first.json()
        hog_flow_id = first.json()["transactional_hog_flow_id"]
        assert second.json()["transactional_hog_flow_id"] == hog_flow_id
        assert second.json()["content"]["email"]["from"] == {"integrationId": self.sender.id}
        workflow = self._workflow(hog_flow_id)
        assert workflow["status"] == "active"
        assert workflow["origin_product"] == "transactional_emails"
        assert workflow["trigger"] == {"type": "api"}
        listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows?type=transactional_email").json()
        assert {flow["id"] for flow in listed["results"]} == {str(self.hog_flow_id), hog_flow_id}

    @parameterized.expand(
        [
            ("marketing_template", "marketing_template"),
            ("deleted_marketing_category", "marketing_template"),
            ("template_without_subject", "template_not_sendable"),
            ("template_without_body", "template_not_sendable"),
            ("unverified_sender", "sender_unavailable"),
            ("custom_address_off_the_chosen_senders_domain", "template_not_sendable"),
        ]
    )
    def test_rejects_making_a_template_transactional_it_cannot_send(
        self, mock_post, _flag, _capture, case, expected_code
    ):
        template = self._template()
        body: dict[str, Any] = {}
        if case in ("marketing_template", "deleted_marketing_category"):
            template.message_category = MessageCategory.objects.create(
                team=self.team,
                key="news",
                name="News",
                category_type=MessageCategoryType.MARKETING,
                deleted=case == "deleted_marketing_category",
            )
        elif case == "template_without_subject":
            template.content = {"email": {"html": "<p>Hi</p>"}}
        elif case == "template_without_body":
            template.content = {"email": {"subject": "Hi"}}
        elif case == "unverified_sender":
            self.sender.config = {"verified": False}
            self.sender.save()
        elif case == "custom_address_off_the_chosen_senders_domain":
            self.sender.config = {"verified": True, "email": "hello@example.com", "domain": "example.com"}
            self.sender.save()
            other = Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id="hello@example.org",
                config={"verified": True, "email": "hello@example.org", "domain": "example.org"},
            )
            sender = {"integrationId": self.sender.id, "email": "security@example.com"}
            template.content = {"email": {**template.content["email"], "from": sender}}
            body = {"from_integration_id": other.id}
        template.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/", body, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        template.refresh_from_db()
        assert template.transactional_hog_flow_id is None

    @patch("products.messaging.backend.services.transactional_email.reload_hog_flows_on_workers")
    def test_saving_a_transactional_template_writes_a_new_workflow_version(self, reload, mock_post, _flag, _capture):
        MessageTemplate.objects.filter(id=self.template.id).update(draft_content={"email": {"subject": "Draft"}})
        security = Integration.objects.create(
            team=self.team, kind="email", integration_id="security@example.com", config={"verified": True}
        )
        email_content = {
            "subject": "A new subject",
            "html": "<p>New</p>",
            # A templated address is only known at send time, so publish accepts it.
            "from": {"integrationId": security.id, "name": "PostHog Security", "email": "{{ variables.alias }}"},
            "replyTo": "security@example.com",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/",
                {"content": {"email": email_content}},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        # Workers reload once the new version is committed, not only from inside the transaction.
        reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(self.hog_flow_id)])
        workflow = self._workflow(self.hog_flow_id)
        assert workflow["version"] == 2
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        assert (email["subject"], email["html"]) == ("A new subject", "<p>New</p>")
        assert email["from"] == {
            "integrationId": security.id,
            "name": "PostHog Security",
            "email": "{{ variables.alias }}",
        }
        assert email["replyTo"] == "security@example.com"
        assert response.json()["draft_content"] is None

    def test_saving_a_draft_leaves_the_sent_email_unchanged(self, mock_post, _flag, _capture):
        # A draft is work in progress, so one the send path would reject still saves.
        draft = {"templating": "liquid", "email": {"subject": "", "html": "<p>Half written</p>"}}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/",
            {"draft_content": draft},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["draft_content"]["email"] == draft["email"]
        assert response.json()["content"]["email"]["subject"] == "Reset your password"
        assert self._workflow(self.hog_flow_id)["version"] == 1

    @parameterized.expand([("marketing_category",), ("no_email_content",)])
    def test_a_template_whose_workflow_was_deleted_takes_edits_it_could_not_send_with(
        self, mock_post, _flag, _capture, edit
    ):
        category = MessageCategory.objects.create(
            team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
        )
        body: dict[str, Any] = (
            {"message_category": str(category.id)} if edit == "marketing_category" else {"content": {}}
        )
        self.client.delete(f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", body, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["transactional_hog_flow_id"] is None

    def test_deleting_a_transactional_template_succeeds(self, mock_post, _flag, _capture):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", {"deleted": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.template.refresh_from_db()
        assert self.template.deleted

    def test_tagging_a_transactional_template_leaves_its_workflow_untouched(self, mock_post, _flag, _capture):
        before = self._workflow(self.hog_flow_id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/",
            {"tags": ["growth"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["tags"] == ["growth"]
        after = self._workflow(self.hog_flow_id)
        assert (after["version"], after["updated_at"]) == (before["version"], before["updated_at"])

    @parameterized.expand(
        [
            ("marketing_category", "marketing_template"),
            ("unverified_sender", "sender_unavailable"),
            ("another_projects_sender", "invalid_input"),
            ("custom_address_off_the_senders_domain", "invalid_input"),
            ("custom_address_that_is_not_an_address", "invalid_input"),
            ("custom_address_too_long", "max_length"),
            ("sender_without_an_id", "invalid_input"),
        ]
    )
    def test_rejects_an_update_that_would_stop_a_transactional_template_sending(
        self, mock_post, _flag, _capture, case, expected_code
    ):
        before = MessageTemplate.objects.get(id=self.template.id)
        if case == "marketing_category":
            category = MessageCategory.objects.create(
                team=self.team, key="news", name="News", category_type=MessageCategoryType.MARKETING
            )
            body: dict[str, Any] = {"message_category": str(category.id)}
        elif case == "sender_without_an_id":
            body = {"content": {"email": {**before.content["email"], "from": {"name": "Security"}}}}
        elif case.startswith("custom_address"):
            self.sender.config = {"verified": True, "email": "hello@example.com", "domain": "example.com"}
            self.sender.save()
            address = {
                "custom_address_off_the_senders_domain": "security@example.org",
                "custom_address_that_is_not_an_address": "Security team",
                "custom_address_too_long": f"{'a' * 250}@example.com",
            }[case]
            email = {**before.content["email"], "from": {"integrationId": self.sender.id, "email": address}}
            body = {"content": {"email": email}}
        else:
            other_team = (
                self.team if case == "unverified_sender" else self.create_team_with_organization(self.organization)
            )
            sender = Integration.objects.create(
                team=other_team, kind="email", integration_id="other@example.com", config={"verified": False}
            )
            email = {**before.content["email"], "from": {"integrationId": sender.id}}
            body = {"content": {"email": email}}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", body, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        after = MessageTemplate.objects.get(id=self.template.id)
        assert (after.message_category_id, after.content) == (None, before.content)
        assert self._workflow(self.hog_flow_id)["version"] == 1


@pytest.mark.ee
@patch(
    "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmailWorkflowAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        self.template = MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content={"email": {"subject": "Reset your password", "html": "<p>Reset</p>"}},
            type="email",
            key="password-reset",
        )
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        self._login_member("member@example.com", {str(self.hog_flow_id): "none"})

    def _login_member(self, email: str, levels: dict[str | None, str]) -> None:
        member = User.objects.create_and_join(self.organization, email, "testtest")
        membership_id = OrganizationMembership.objects.get(user=member, organization=self.organization).id
        for resource_id, access_level in levels.items():
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                resource_id=resource_id,
                access_level=access_level,
                organization_member_id=membership_id,
            )
        self.client.force_login(member)

    @parameterized.expand(
        [
            ("send", "post", "messaging_templates/{id}/send/", {"to": "user@example.com"}),
            (
                "send_email",
                "post",
                "messaging/send/email/",
                {"to": "user@example.com", "template": {"key": "password-reset"}},
            ),
            (
                "send_rendered_email",
                "post",
                "messaging/send/email/",
                {"to": "user@example.com", "template_key": "password-reset", "subject": "Hi", "html": "<p>Hi</p>"},
            ),
            (
                "update",
                "patch",
                "messaging_templates/{id}/",
                {"content": {"email": {"subject": "New", "html": "<p>New</p>"}}},
            ),
            (
                "save_draft",
                "patch",
                "messaging_templates/{id}/",
                {"draft_content": {"email": {"subject": "Draft", "html": "<p>Draft</p>"}}},
            ),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_send_or_change_it(self, mock_post, _flag, _name, method, path, body):
        url = f"/api/projects/{self.team.id}/{path.format(id=self.template.id)}"

        response = getattr(self.client, method)(url, body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("update", {"content": {"email": {"subject": "New", "html": "<p>New</p>"}}}),
            ("save_draft", {"draft_content": {"email": {"subject": "Draft", "html": "<p>Draft</p>"}}}),
        ]
    )
    def test_a_member_denied_a_workflow_linked_mid_request_cannot_change_the_template(self, _post, _flag, _name, edit):
        MessageTemplate.objects.filter(id=self.template.id).update(transactional_hog_flow_id=None)
        original = MessageTemplatesViewSet.dangerously_get_object

        def read_then_link_the_workflow(viewset: MessageTemplatesViewSet) -> Any:
            template = original(viewset)
            MessageTemplate.objects.filter(id=template.id).update(transactional_hog_flow_id=self.hog_flow_id)
            return template

        with patch.object(MessageTemplatesViewSet, "dangerously_get_object", read_then_link_the_workflow):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/", edit, format="json"
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        self.template.refresh_from_db()
        assert (self.template.content["email"]["subject"], self.template.draft_content) == (
            "Reset your password",
            None,
        )

    @parameterized.expand(
        [
            ("unchanged_content", False, {"content_hash": PASSWORD_RESET_HASH}),
            (
                "superseded_content",
                True,
                {"content_hash": "v1:" + "0" * 64, "superseded_content_hashes": [PASSWORD_RESET_HASH]},
            ),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_upload_to_it(
        self, mock_post, _flag, _name, if_not_superseded, stored_hashes
    ):
        MessageTemplate.objects.filter(id=self.template.id).update(managed_by="code", **stored_hashes)

        with patch(
            "products.messaging.backend.presentation.views.transactional_email_api.posthoganalytics.capture"
        ) as capture:
            response = self.client.put(
                f"/api/projects/{self.team.id}/messaging_templates/by_key/password-reset/",
                {
                    "name": "Password reset",
                    "subject": "Reset your password",
                    "html": "<p>Reset</p>",
                    "source": {"repository": "github.com/example/other"},
                    "if_not_superseded": if_not_superseded,
                },
                format="json",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        self.template.refresh_from_db()
        assert self.template.source_repository is None
        uploaded_events = [
            c for c in capture.call_args_list if c.kwargs["event"] == "transactional email template uploaded"
        ]
        assert [e.kwargs["properties"]["error_code"] for e in uploaded_events] == ["permission_denied"]

    @parameterized.expand([("unlinked", None), ("linked_to_a_deleted_workflow", uuid4())])
    def test_editor_access_to_one_workflow_cannot_create_another(self, mock_post, _flag, _name, linked_hog_flow_id):
        self._login_member("viewer@example.com", {None: "viewer", str(self.hog_flow_id): "editor"})
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Welcome",
            content={"email": {"subject": "Welcome", "html": "<p>Hi</p>"}},
            type="email",
            transactional_hog_flow_id=linked_hog_flow_id,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/", {}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        template.refresh_from_db()
        assert template.transactional_hog_flow_id == linked_hog_flow_id

    def test_a_member_who_cannot_create_workflows_cannot_send_under_a_new_key(self, mock_post, _flag):
        self._login_member("viewer@example.com", {None: "viewer", str(self.hog_flow_id): "editor"})
        workflows_before = HogFlow.objects.filter(team=self.team).count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {"to": "user@example.com", "template_key": "welcome", "subject": "Welcome", "html": "<p>Hi</p>"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert HogFlow.objects.filter(team=self.team).count() == workflows_before
        assert not TransactionalEmailKey.objects.for_team(self.team.id).exists()
        mock_post.assert_not_called()
