import re
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import MagicMock, _Call, call, patch

from django.conf import settings
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

import requests
import responses
from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient
from structlog.testing import capture_logs

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, ProjectSecretAPIKey, Team, User
from posthog.models.integration import Integration
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret
from posthog.security.outbound_proxy import internal_requests
from posthog.test.waiting import wait_until

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.facade.transactional_email import report_first_code_send
from products.messaging.backend.models.first_code_send import FirstCodeSend
from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.presentation.views.message_templates import (
    CODE_SEND_CATEGORIES_FLAG,
    CODE_SEND_FIELDS,
    EMAIL_FROM_CODE_FLAG,
    TRANSACTIONAL_EMAIL_API_FLAG,
)
from products.messaging.backend.services import send_categories, transactional_email
from products.messaging.backend.services.code_email_source import SOURCE_DETECTION_FLAG
from products.messaging.backend.services.transactional_email import TransactionalEmailStage, make_transactional
from products.messaging.backend.tasks.tasks import detect_code_email_source_task
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
from products.workflows.backend.facade.models import HogFlow
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig

CSV, NOTES = "c" * 64, "d" * 64
TWO_FILES = [{"sha256": CSV, "filename": "a.csv"}, {"sha256": NOTES, "filename": "notes.txt"}]
MARKETING_SEND = {
    "category": {"key": "newsletter", "type": "marketing", "name": "Newsletter"},
    "html": '<a href="{{ unsubscribe_url }}">Unsubscribe</a>',
}
CDP_ACCEPTS = {"return_value": MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})}
CDP_REPLAYS = MagicMock(status_code=202, json=lambda: {"invocation_id": "first-send", "replayed": True})


@frozen
class CapturedFirstCodeSend:
    distinct_id: str | None
    properties: dict[str, Any]
    organization_id: str
    project: str


def _stage_counts() -> dict[str, float]:
    return {
        stage: REGISTRY.get_sample_value("messaging_transactional_email_stage_duration_seconds_count", {"stage": stage})
        or 0
        for stage in get_args(TransactionalEmailStage)
    }


CDP_SEND_ROUTE = re.compile(r".*/api/projects/(?P<team_id>\d+)/hog_flows/[^/]+/transactional_email(/send)?$")
ACCEPTED_REQUEST_KEYS: dict[str, set[str] | None] = {
    "to": None,
    "distinct_id": None,
    "variables": None,
    "idempotency_key": None,
    "send": None,
    "message_category": {"id", "type"},
}
ACCEPTED_SEND_KEYS: dict[str, set[str] | None] = {
    "content": {"subject", "html", "text"},
    "from": {"integrationId", "email", "name"},
    "replyTo": None,
    "cc": None,
    "bcc": None,
    "tracking": {"captureEngagement"},
    "attachments": None,
}
ACCEPTED_ATTACHMENT_KEYS = {"sha256", "filename", "content_type", "content_id"}
WELCOME_DELIVERED = {
    "subject": "Welcome, Jane",
    "html": "<p>Hi Jane</p>",
    "text": "Hi Jane",
    "captureEngagement": True,
}


class CapturedEvents:
    def __init__(self, capture: MagicMock) -> None:
        self._events: list[dict[str, Any]] = []
        capture.side_effect = self._capture

    def _capture(self, **event: Any) -> str:
        self._events.append(event)
        return str(uuid4())

    def properties(self, event: str) -> list[dict[str, Any]]:
        return [captured["properties"] for captured in self._events if captured.get("event") == event]


class FakeCdpApi:
    def __init__(self, refusal: tuple[int, str] | None = None, *, takes_attachments: bool = True) -> None:
        self.received: list[dict[str, Any]] = []
        self._queued: list[dict[str, Any]] = []
        self._refusal = refusal
        self._accepted = {
            field: keys for field, keys in ACCEPTED_SEND_KEYS.items() if takes_attachments or field != "attachments"
        }

    @contextmanager
    def serving(self, client_post: MagicMock) -> Iterator["FakeCdpApi"]:
        client_post.side_effect = partial(requests.Session.post, internal_requests)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            http.add_callback(responses.POST, CDP_SEND_ROUTE, self._send)
            yield self

    def _send(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        payload = json.loads(request.body or "{}")
        self.received.append(payload)
        issues = _unrecognized_keys(payload, ACCEPTED_REQUEST_KEYS, [])
        if "send" in payload:
            issues += self._unrecognized_send_keys(payload["send"])
            if not isinstance(payload["send"].get("tracking", {}).get("captureEngagement"), bool):
                issues.append({"code": "invalid_type", "path": ["send", "tracking", "captureEngagement"]})
        if issues:
            return 400, {}, json.dumps({"error": json.dumps(issues)})
        refusal = self._refusal or self._opt_out_refusal(request.url or "", payload)
        if refusal:
            return refusal[0], {}, json.dumps({"error": refusal[1]})
        self._queued.append(payload)
        return 202, {}, json.dumps({"invocation_id": f"invocation-{len(self._queued)}"})

    def emails(self) -> list[dict[str, Any]]:
        return [self._email(payload["send"]) for payload in self._queued]

    def categories(self) -> list[dict[str, str] | None]:
        return [payload.get("message_category") for payload in self._queued]

    @staticmethod
    def _email(send: dict[str, Any]) -> dict[str, Any]:
        email = {**send["content"], "captureEngagement": send["tracking"]["captureEngagement"]}
        email.update({field: send[field] for field in ("from", "replyTo", "cc", "bcc", "attachments") if field in send})
        return email

    def deliver(self) -> list[tuple[str, str]]:
        delivered, self._queued = self._queued, []
        return [
            ("$workflows_email_sent", payload["distinct_id"])
            for payload in delivered
            if payload["send"]["tracking"]["captureEngagement"] is not False
        ]

    def _unrecognized_send_keys(self, send: dict[str, Any]) -> list[dict[str, Any]]:
        issues = _unrecognized_keys(send, self._accepted, ["send"])
        if "attachments" in self._accepted:
            for index, file in enumerate(send.get("attachments") or []):
                if file.keys() - ACCEPTED_ATTACHMENT_KEYS:
                    issues.append(
                        {
                            "code": "unrecognized_keys",
                            "keys": sorted(file.keys() - ACCEPTED_ATTACHMENT_KEYS),
                            "path": ["send", "attachments", index],
                        }
                    )
        return issues

    @staticmethod
    def _opt_out_refusal(url: str, payload: dict[str, Any]) -> tuple[int, str] | None:
        category = payload.get("message_category") or {}
        if category.get("type") != "marketing":
            return None
        route = CDP_SEND_ROUTE.search(url)
        assert route is not None
        recipient = MessageRecipientPreference.objects.filter(
            team_id=int(route["team_id"]), identifier=payload["to"]
        ).first()
        preferences = recipient.preferences if recipient else {}
        if "OPTED_OUT" in (preferences.get(category["id"]), preferences.get("$all")):
            return 422, "recipient_opted_out"
        return None


def _unrecognized_keys(value: dict[str, Any], accepted: dict[str, Any], path: list[str]) -> list[dict[str, Any]]:
    issues = [{"code": "unrecognized_keys", "keys": [key], "path": path} for key in value.keys() - accepted.keys()]
    for field, allowed in accepted.items():
        if allowed is not None and isinstance(value.get(field), dict) and value[field].keys() - allowed:
            issues.append(
                {"code": "unrecognized_keys", "keys": sorted(value[field].keys() - allowed), "path": [*path, field]}
            )
    return issues


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
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
        self.template = self._template()
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

    def _use_fakes(self, cdp_post: MagicMock, capture: MagicMock) -> None:
        self.cdp = self.enterContext(FakeCdpApi().serving(cdp_post))
        self.events = CapturedEvents(capture)

    def _template(self, content: dict | None = None) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content=content
            or {"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
        )

    def _workflow(self, hog_flow_id) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{hog_flow_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _cdp_accepts(self, mock_post: MagicMock, invocation_id: str = "invocation-1") -> None:
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": invocation_id})

    def _send(self, client: APIClient, route: str, body: dict, **kwargs: Any) -> Any:
        if route == "send_email":
            return client.post(self.send_email_url, self._flat(body), format="json", **kwargs)
        if route == "send_email_nested":
            body = {**body, "template": {"id": str(self.template.id)}}
            return client.post(self.send_email_url, body, format="json", **kwargs)
        return client.post(self.url, body, format="json", **kwargs)

    def _flat(self, body: dict) -> dict:
        flat = {k: v for k, v in body.items() if k != "identifiers"}
        if "identifiers" in body:
            flat["distinct_id"] = body["identifiers"]["distinct_id"]
        return {**flat, "template_id": str(self.template.id)}

    def _psak_client(
        self,
        scopes: list[str],
        created_by: User | None = None,
        label: str = "transactional email",
        team: Team | None = None,
    ) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label=label,
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
            created_by=created_by,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    @parameterized.expand(
        [
            ("with_distinct_id", "template", {"identifiers": {"distinct_id": "user-1"}}, "user-1"),
            # Without a distinct_id the recipient's address is the person the send is tracked against.
            ("email_only", "template", {}, "user@example.com"),
            ("with_distinct_id_on_send_email", "send_email", {"distinct_id": "user-1"}, "user-1"),
            ("email_only_on_send_email", "send_email", {}, "user@example.com"),
            (
                "with_distinct_id_on_send_email_nested",
                "send_email_nested",
                {"identifiers": {"distinct_id": "user-1"}},
                "user-1",
            ),
            ("email_only_on_send_email_nested", "send_email_nested", {}, "user@example.com"),
        ]
    )
    def test_runs_the_templates_workflow_for_the_recipient(
        self, mock_post, _flag, capture, _name, route, recipient, expected_distinct_id
    ):
        self._cdp_accepts(mock_post)
        body = {**{k: v for k, v in self.body.items() if k != "identifiers"}, **recipient}
        client = self._psak_client(["hog_flow:write"])
        stages_before = _stage_counts()

        response = self._send(client, route, body)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        stages_after = _stage_counts()
        assert {stage: stages_after[stage] - stages_before[stage] for stage in stages_after} == dict.fromkeys(
            stages_after, 1
        )
        assert response.json() == {"message_id": "invocation-1", "replayed": False}
        assert capture.call_args.kwargs["properties"]["route"] == route.removesuffix("_nested")
        assert mock_post.call_args.args[0].endswith(
            f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow_id}/transactional_email"
        )
        assert mock_post.call_args.kwargs["json"] == {
            "to": "user@example.com",
            "distinct_id": expected_distinct_id,
            "variables": {"link": "https://example.com/reset", "nickname": None},
        }

    @parameterized.expand([("template",), ("send_email",)])
    def test_a_project_secret_api_key_send_reads_the_key_template_and_workflow_once(
        self, mock_post, _flag, _capture, route
    ):
        self._cdp_accepts(mock_post)
        client = self._psak_client(["hog_flow:write"])
        # The first send also records when the key was last used.
        assert self._send(client, route, self.body).status_code == status.HTTP_202_ACCEPTED

        # The key with its team and organization, the template, and the template's workflow.
        with self.assertNumQueries(3):
            response = self._send(client, route, self.body)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

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
            ("send_with_write_scope", "post", "send/", ["hog_flow:write"], status.HTTP_202_ACCEPTED),
            ("send_with_read_scope", "post", "send/", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
            ("send_with_preference_scope", "post", "send/", ["messaging_preference:write"], status.HTTP_403_FORBIDDEN),
            ("send_with_send_scope", "post", "send/", ["transactional_email:write"], status.HTTP_202_ACCEPTED),
            ("send_with_status_scope", "post", "send/", ["transactional_email:read"], status.HTTP_403_FORBIDDEN),
            ("send_email_with_write_scope", "post", "send_email", ["hog_flow:write"], status.HTTP_202_ACCEPTED),
            ("send_email_with_read_scope", "post", "send_email", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
            (
                "send_email_with_preference_scope",
                "post",
                "send_email",
                ["messaging_preference:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "send_email_with_send_scope",
                "post",
                "send_email",
                ["transactional_email:write"],
                status.HTTP_202_ACCEPTED,
            ),
            (
                "send_email_with_status_scope",
                "post",
                "send_email",
                ["transactional_email:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            ("retrieve_is_not_a_psak_action", "get", "", ["hog_flow:write"], status.HTTP_403_FORBIDDEN),
            (
                "make_transactional_is_not_a_psak_action",
                "post",
                "make_transactional/",
                ["hog_flow:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "make_transactional_is_not_a_psak_action_with_send_scope",
                "post",
                "make_transactional/",
                ["transactional_email:write"],
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    def test_project_secret_api_key_can_only_send(
        self, mock_post, _flag, _capture, _name, method, suffix, scopes, expected_status
    ):
        self._cdp_accepts(mock_post)
        if suffix == "send_email":
            url, body = self.send_email_url, self._flat(self.body)
        elif suffix == "code_send":
            url, body = self.send_email_url, self._code_send()
        else:
            url, body = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/{suffix}", self.body

        response = getattr(self._psak_client(scopes), method)(url, body if method == "post" else None, format="json")

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("send_scope", "template", ["transactional_email:write"], "transactional_email"),
            ("workflow_scope", "template", ["hog_flow:write"], "hog_flow"),
            (
                "both_scopes",
                "template",
                ["hog_flow:write", "transactional_email:write"],
                "transactional_email",
            ),
        ]
    )
    def test_records_the_scope_that_authorized_the_send(
        self, mock_post, _flag, capture, _name, route, scopes, expected_authorized_by
    ):
        self._cdp_accepts(mock_post)

        response = self._send(self._psak_client(scopes), route, self.body)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert capture.call_args.kwargs["properties"]["authorized_by"] == expected_authorized_by

    @parameterized.expand(
        [
            ("send_scope", ["transactional_email:write"], status.HTTP_200_OK, False),
            ("workflow_scope", ["hog_flow:write"], status.HTTP_200_OK, True),
            ("send_and_workflow_read_scopes", ["transactional_email:write", "hog_flow:read"], status.HTTP_200_OK, True),
            ("status_scope", ["transactional_email:read"], status.HTTP_403_FORBIDDEN, False),
        ]
    )
    def test_making_a_template_transactional_needs_the_send_scope(
        self, _mock_post, _flag, _capture, _name, scopes, expected_status, returns_content
    ):
        template = self._template()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(scopes)}")

        response = client.post(
            f"/api/projects/{self.team.id}/messaging_templates/{template.id}/make_transactional/", {}, format="json"
        )

        assert response.status_code == expected_status, response.json()
        template.refresh_from_db()
        assert (template.transactional_hog_flow_id is not None) == (expected_status == status.HTTP_200_OK)
        if expected_status == status.HTTP_200_OK:
            body = response.json()
            assert body["transactional_hog_flow_id"] == str(template.transactional_hog_flow_id)
            assert ("content" in body, "draft_content" in body) == (returns_content, returns_content)

    def test_a_personal_api_key_with_the_send_scope_cannot_change_the_template(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(['transactional_email:write'])}"
        )
        template_url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/"

        send = client.post(self.url, self.body, format="json")
        edit = client.patch(template_url, {"name": "Renamed"}, format="json")

        assert send.status_code == status.HTTP_202_ACCEPTED, send.json()
        assert edit.status_code == status.HTTP_403_FORBIDDEN, edit.json()

    @parameterized.expand(
        [
            ("not_transactional", "template_not_transactional"),
            ("workflow_archived", "transactional_email_paused"),
            ("category_turned_marketing", "marketing_template"),
            ("liquid_in_recipient", "invalid_recipient"),
            ("idempotency_key_with_spaces", "invalid_idempotency_key"),
            ("idempotency_key_too_long", "invalid_idempotency_key"),
        ]
    )
    def test_rejects_a_send_it_cannot_make(self, mock_post, _flag, _capture, case, expected_code):
        url, body, headers = self.url, dict(self.body), {}
        if case == "not_transactional":
            url = f"/api/projects/{self.team.id}/messaging_templates/{self._template().id}/send/"
        elif case == "workflow_archived":
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

        response = self.client.post(url, body, format="json", headers=headers)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert response.json()["type"] == "invalid_request"
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("timeout", requests.ReadTimeout(), "timeout", None),
            ("connect_timeout", requests.ConnectTimeout(), "timeout", None),
            ("connection_error", requests.ConnectionError(), "connection_error", None),
            ("cdp_api_error", MagicMock(status_code=500, json=dict), "5xx", None),
            (
                "intake_unavailable",
                MagicMock(status_code=503, json=lambda: {"error": "intake_unavailable"}),
                "5xx",
                "intake_unavailable",
            ),
            (
                "workflow_not_found",
                MagicMock(status_code=404, json=lambda: {"error": "Workflow not found"}),
                "4xx",
                "Workflow not found",
            ),
        ]
    )
    def test_a_send_the_pipeline_does_not_confirm_is_unavailable(
        self, mock_post, _flag, _capture, _name, outcome, expected_result, expected_refusal_code
    ):
        if isinstance(outcome, Exception):
            mock_post.side_effect = outcome
        else:
            mock_post.return_value = outcome
        metric = "messaging_transactional_email_cdp_requests_total"
        before = REGISTRY.get_sample_value(metric, {"result": expected_result}) or 0

        with capture_logs() as logs:
            response = self.client.post(self.url, self.body, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "delivery_unavailable"
        assert REGISTRY.get_sample_value(metric, {"result": expected_result}) == before + 1
        if not isinstance(outcome, Exception):
            rejected = [log for log in logs if log["event"] == "transactional_email_queue_rejected"]
            assert [log["refusal_code"] for log in rejected] == [expected_refusal_code]

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
            ("quota_limited", 429, 429, "quota_limited"),
            ("idempotency_key_in_flight", 409, 409, "idempotency_key_in_flight"),
            ("idempotency_key_reused", 422, 422, "idempotency_key_reused"),
            ("sending_suspended", 422, 422, "sending_suspended"),
            ("sending_paused", 422, 422, "sending_paused"),
            ("recipient_suppressed", 422, 422, "recipient_suppressed"),
            ("recipient_unreachable", 422, 422, "recipient_unreachable"),
            ("not_sendable", 400, 400, "transactional_email_paused"),
            ("invalid_request", 400, 400, "invalid_request"),
            ("a 400 without a known code", 400, 400, "invalid_request"),
            ("Request entity too large", 413, 400, "content_too_large"),
            ("message_too_large", 413, 400, "content_too_large"),
        ]
    )
    def test_reports_a_send_the_pipeline_refuses(
        self, mock_post, _flag, _capture, pipeline_code, pipeline_status, expected_status, expected_code
    ):
        mock_post.return_value = MagicMock(status_code=pipeline_status, json=lambda: {"error": pipeline_code})

        response = self.client.post(self.url, self.body, format="json", headers={"Idempotency-Key": "key-1"})

        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code

    @parameterized.expand(
        [
            ("send", "messaging_templates/{template_id}/send/"),
            ("make_transactional", "messaging_templates/{template_id}/make_transactional/"),
            ("send_email", "messaging/send/email/"),
        ]
    )
    def test_is_hidden_while_the_flag_is_off(self, mock_post, flag, _capture, _name, path):
        flag.return_value = False

        response = self.client.post(
            f"/api/projects/{self.team.id}/{path.format(template_id=self.template.id)}",
            self._flat(self.body),
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("unknown_template", lambda test: str(uuid4()), status.HTTP_404_NOT_FOUND),
            (
                "another_projects_template",
                lambda test: str(test._other_team_template().id),
                status.HTTP_404_NOT_FOUND,
            ),
            ("no_template", lambda test: None, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_send_email_sends_only_a_template_of_this_project(
        self, mock_post, _flag, _capture, _name, template, expected_status
    ):
        self._cdp_accepts(mock_post)
        ref = template(self)
        body = {**self.body, "template_id": ref} if ref else self.body

        response = self._psak_client(["hog_flow:write"]).post(self.send_email_url, body, format="json")

        assert response.status_code == expected_status, response.json()
        mock_post.assert_not_called()

    def _code_send(self, **fields: Any) -> dict[str, Any]:
        return {
            "to": "user@example.com",
            "distinct_id": "user-1",
            "template_key": "welcome",
            "subject": "Welcome, Jane",
            "html": "<p>Hi Jane</p>",
            **fields,
        }

    @parameterized.expand([("new_key", "welcome"), ("key_that_names_a_template", "password-reset")])
    def test_a_code_send_goes_out_as_is_under_the_keys_workflow(self, mock_post, _flag, capture, _name, key):
        MessageTemplate.objects.filter(id=self.template.id).update(key="password-reset")
        self._cdp_accepts(mock_post)
        templates_before = MessageTemplate.objects.filter(team=self.team).count()
        psak = self._psak_client(["hog_flow:write"])

        first = psak.post(self.send_email_url, self._code_send(template_key=key), format="json")
        second = psak.post(self.send_email_url, self._code_send(template_key=key, subject="Again"), format="json")

        assert first.status_code == status.HTTP_202_ACCEPTED, first.json()
        assert first.json() == {"message_id": "invocation-1", "replayed": False}
        assert second.status_code == status.HTTP_202_ACCEPTED, second.json()
        first_url, second_url = (call.args[0] for call in mock_post.call_args_list)
        assert first_url == second_url
        assert first_url.endswith("/transactional_email/send")
        hog_flow_id = first_url.split("/hog_flows/")[1].split("/")[0]
        if key == "password-reset":
            assert hog_flow_id == str(self.hog_flow_id)
        else:
            assert TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).get(
                key=key
            ).hog_flow_id == UUID(hog_flow_id)
            listed = self.client.get(f"/api/projects/{self.team.id}/hog_flows/").json()["results"]
            assert hog_flow_id not in {workflow["id"] for workflow in listed}
        email_step = HogFlow.objects.get(team=self.team, id=hog_flow_id).actions[1]["config"]
        assert (email_step["sensitive"], email_step.get("template_key")) == (
            (True, "welcome") if key == "welcome" else (False, None)
        )
        assert json.loads(mock_post.call_args_list[0].kwargs["data"]) == {
            "to": "user@example.com",
            "distinct_id": "user-1",
            "variables": {},
            "send": {
                "content": {"subject": "Welcome, Jane", "html": "<p>Hi Jane</p>", "text": "Hi Jane"},
                "from": {"integrationId": self.sender.id},
                "tracking": {"captureEngagement": True},
            },
        }
        assert MessageTemplate.objects.filter(team=self.team).count() == templates_before
        reported = capture.call_args.kwargs["properties"]
        assert (reported["route"], reported["addressed_by"], reported["outcome"]) == (
            "send_email",
            "template_key",
            "queued",
        )

    @parameterized.expand(
        [
            ("queued", None, True),
            ("queue_unavailable", ConnectionError("broker unreachable"), True),
            ("detection_off", None, False),
        ]
    )
    def test_a_new_keys_first_send_queues_source_detection_after_commit(
        self, mock_post, flag, _capture, _name, queue_error, detection_on
    ):
        flag.side_effect = lambda key, *_, **__: detection_on or key != SOURCE_DETECTION_FLAG
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])

        def detection_checks() -> list[_Call]:
            return [check for check in flag.call_args_list if check.args[0] == SOURCE_DETECTION_FLAG]

        with patch.object(detect_code_email_source_task, "apply_async", side_effect=queue_error) as queue:
            with self.captureOnCommitCallbacks(execute=True):
                first = psak.post(self.send_email_url, self._code_send(), format="json")
                assert queue.call_count == 0
                assert detection_checks() == []
            with self.captureOnCommitCallbacks(execute=True):
                second = psak.post(self.send_email_url, self._code_send(), format="json")

        assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED, first.json()
        assert [check.kwargs["only_evaluate_locally"] for check in detection_checks()] == [True]
        key = TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).get(key="welcome")
        assert queue.call_args_list == ([call(args=(self.team.id, str(key.id)), retry=False)] if detection_on else [])

    def test_each_environment_of_a_project_keeps_its_own_workflow_for_a_key(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        env_sender = Integration.objects.create(
            team=env, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(env.id, env_sender.id)
        clients = {
            self.team.id: self._psak_client(["hog_flow:write"]),
            env.id: self._psak_client(["hog_flow:write"], team=env),
        }

        for team_id in (self.team.id, env.id, self.team.id, env.id):
            response = clients[team_id].post(
                f"/api/projects/{team_id}/messaging/send/email/", self._code_send(), format="json"
            )
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

        workflow_ids = [call.args[0].split("/hog_flows/")[1].split("/")[0] for call in mock_post.call_args_list]
        assert workflow_ids[0] == workflow_ids[2]
        assert workflow_ids[1] == workflow_ids[3]
        assert workflow_ids[0] != workflow_ids[1]

    def test_a_known_key_keeps_sending_at_the_key_limit_while_a_new_key_is_refused(self, mock_post, _flag, capture):
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])
        with patch.object(transactional_email, "TRANSACTIONAL_EMAIL_KEY_LIMIT", 1):
            first = psak.post(self.send_email_url, self._code_send(template_key="welcome"), format="json")
            deleted_workflow_id = (
                TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).get(key="welcome").hog_flow_id
            )
            HogFlow.objects.filter(team=self.team, id=deleted_workflow_id).delete()

            second = psak.post(self.send_email_url, self._code_send(template_key="welcome"), format="json")
            new_key = psak.post(self.send_email_url, self._code_send(template_key="receipt"), format="json")

        assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED, second.json()
        new_workflow_id = (
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).get(key="welcome").hog_flow_id
        )
        assert new_workflow_id != deleted_workflow_id
        assert f"/hog_flows/{new_workflow_id}/" in mock_post.call_args_list[1].args[0]
        assert new_key.status_code == status.HTTP_400_BAD_REQUEST, new_key.json()
        assert new_key.json()["code"] == "too_many_keys"
        assert capture.call_args.kwargs["properties"]["error_code"] == "too_many_keys"
        assert mock_post.call_count == 2
        assert not TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(key="receipt").exists()
        assert not HogFlow.objects.filter(team=self.team, name="receipt").exists()

    @parameterized.expand(
        [
            (
                "sender_and_reply_to",
                {"text": "Hi", "from": "Example <security@example.com>", "reply_to": ["help@example.com"]},
                {
                    **WELCOME_DELIVERED,
                    "text": "Hi",
                    "from": {"email": "security@example.com", "name": "Example"},
                    "replyTo": ["help@example.com"],
                },
            ),
            (
                "without_engagement_capture",
                {"capture_engagement": False},
                {**WELCOME_DELIVERED, "captureEngagement": False},
            ),
            (
                "text_only",
                {"html": "", "text": "Hi"},
                {"subject": "Welcome, Jane", "text": "Hi", "captureEngagement": True},
            ),
            ("null_copies_and_attachments", {"cc": None, "bcc": None, "attachments": None}, WELCOME_DELIVERED),
            ("key_of_256_characters", {"template_key": "k" * 256}, WELCOME_DELIVERED),
            (
                "cc_and_bcc",
                {"cc": "copy@example.com", "bcc": ["audit@example.com", "archive@example.com"]},
                {**WELCOME_DELIVERED, "cc": ["copy@example.com"], "bcc": ["audit@example.com", "archive@example.com"]},
            ),
            (
                "uploaded_attachments",
                {
                    "attachments": [
                        {"sha256": CSV, "filename": "a.csv", "content_type": "text/csv", "content_id": "a"},
                        {"sha256": NOTES, "filename": "notes.txt"},
                    ]
                },
                {
                    **WELCOME_DELIVERED,
                    "attachments": [
                        {"sha256": CSV, "filename": "a.csv", "content_type": "text/csv", "content_id": "a"},
                        {"sha256": NOTES, "filename": "notes.txt"},
                    ],
                },
            ),
        ]
    )
    def test_a_code_send_carries_what_the_caller_set(self, mock_post, _flag, _capture, _name, fields, delivered):
        newer_default = Integration.objects.create(
            team=self.team, kind="email", integration_id="news@example.com", config={"verified": True}
        )
        TeamWorkflowsConfig.objects.filter(team_id=self.team.id).update(default_email_integration_id=newer_default.id)

        with FakeCdpApi().serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(**fields), format="json"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        sender = {**delivered.get("from", {}), "integrationId": newer_default.id}
        assert cdp.emails() == [{**delivered, "from": sender}]

    UNSUBSCRIBE_HTML = '<a href="{{ unsubscribe_url }}">Unsubscribe</a>'
    NEWSLETTER = {"key": "newsletter", "type": "marketing", "name": "Newsletter"}

    def _at_key_limit(self) -> None:
        patcher = patch.object(transactional_email, "TRANSACTIONAL_EMAIL_KEY_LIMIT", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _archived_key_workflow(self) -> None:
        hog_flow_id = transactional_email._key_workflow_id(self.team.id, self._code_send()["template_key"])
        HogFlow.objects.filter(team=self.team, id=hog_flow_id).update(status="archived")

    def _category(self, key: str = "newsletter", **fields: Any) -> MessageCategory:
        return MessageCategory.objects.create(
            team=self.team,
            key=key,
            name=fields.pop("name", "Newsletter"),
            category_type=fields.pop("category_type", MessageCategoryType.MARKETING),
            **fields,
        )

    @parameterized.expand(
        [
            ("left_out", {}, None),
            ("null", {"category": None}, None),
            ("transactional", {"category": "transactional", "html": UNSUBSCRIBE_HTML}, None),
            ("marketing", {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML}, "marketing"),
            (
                "transactional_category_needs_no_link",
                {"category": {"key": "receipts", "type": "transactional", "name": "Receipts"}},
                "transactional",
            ),
        ]
    )
    def test_a_code_sends_category_decides_how_it_goes_out(self, cdp_post, _flag, capture, _name, fields, kind):
        self._use_fakes(cdp_post, capture)

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url, self._code_send(**fields), format="json"
        )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        if kind is None:
            assert self.cdp.categories() == [None]
            assert not MessageCategory.objects.filter(team=self.team).exists()
        else:
            category = MessageCategory.objects.get(team=self.team, key=fields["category"]["key"])
            assert self.cdp.categories() == [{"id": str(category.id), "type": kind}]
            assert category.category_type == kind
        [email] = self.cdp.emails()
        assert ("{{ unsubscribe_url }}" in email["text"]) == (kind == "marketing")
        assert [send["category_type"] for send in self.events.properties("transactional email api send")] == [
            kind or "transactional"
        ]

    @parameterized.expand(
        [
            ("link_in_the_html", {"html": UNSUBSCRIBE_HTML}, status.HTTP_202_ACCEPTED),
            ("link_in_the_text_of_an_email_without_html", {"html": "", "text": "Bye: {{unsubscribe_url}}"}, 202),
            ("no_link", {"html": "<p>Hi</p>", "text": "Hi"}, status.HTTP_400_BAD_REQUEST),
            ("link_only_in_the_text_beside_html", {"html": "<p>Hi</p>", "text": "{{ unsubscribe_url }}"}, 400),
        ]
    )
    def test_a_marketing_code_send_needs_the_unsubscribe_placeholder(
        self, cdp_post, _flag, capture, _name, body, expected_status
    ):
        self._use_fakes(cdp_post, capture)

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url, self._code_send(category=self.NEWSLETTER, **body), format="json"
        )

        assert response.status_code == expected_status, response.json()
        sent = expected_status == status.HTTP_202_ACCEPTED
        assert len(self.cdp.emails()) == (1 if sent else 0)
        assert MessageCategory.objects.filter(team=self.team, key="newsletter").exists() == sent
        if not sent:
            assert response.json()["code"] == "unsubscribe_link_required"

    @parameterized.expand(
        [
            ("unknown_key_creates_it", None, ("Newsletter", "Monthly news")),
            (
                "existing_category_keeps_its_name_and_description",
                {"name": "News", "description": "Old"},
                ("News", "Old"),
            ),
            ("archived_category_is_restored", {"name": "News", "deleted": True}, ("News", "")),
        ]
    )
    def test_a_code_send_creates_its_category_by_key_and_never_renames_it(
        self, cdp_post, _flag, capture, _name, existing, expected
    ):
        self._use_fakes(cdp_post, capture)
        before = self._category(**existing) if existing is not None else None

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url,
            self._code_send(category={**self.NEWSLETTER, "description": "Monthly news"}, html=self.UNSUBSCRIBE_HTML),
            format="json",
        )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        category = MessageCategory.objects.get(team=self.team, key="newsletter")
        if before is not None:
            assert category.id == before.id
        assert (category.name, category.description, category.deleted) == (*expected, False)
        assert self.cdp.categories() == [{"id": str(category.id), "type": "marketing"}]

    @parameterized.expand(
        [
            (
                "existing_category_of_another_type",
                lambda test: test._category(category_type=MessageCategoryType.TRANSACTIONAL),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "category_mismatch",
            ),
            (
                "archived_category_of_another_type",
                lambda test: test._category(category_type=MessageCategoryType.TRANSACTIONAL, deleted=True),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "category_mismatch",
            ),
            (
                "copies_on_marketing",
                None,
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML, "cc": ["copy@example.com"]},
                "copies_not_allowed",
            ),
            (
                "blind_copies_on_marketing",
                None,
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML, "bcc": ["copy@example.com"]},
                "copies_not_allowed",
            ),
            (
                "category_limit_reached",
                lambda test: test._category(key="promos"),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "too_many_categories",
            ),
            (
                "archived_category_beyond_the_limit",
                lambda test: (test._category(key="promos"), test._category(deleted=True)),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "too_many_categories",
            ),
            (
                "key_limit_reached",
                lambda test: test._at_key_limit(),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "too_many_keys",
            ),
            (
                "workflow_archived",
                lambda test: test._archived_key_workflow(),
                {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML},
                "transactional_email_paused",
            ),
            ("bare_key", None, {"category": "newsletter"}, "invalid_input"),
            (
                "opt_out_sentinel_key",
                None,
                {"category": {**NEWSLETTER, "key": "$all"}, "html": UNSUBSCRIBE_HTML},
                "invalid_input",
            ),
            (
                "missing_name",
                None,
                {"category": {"key": "newsletter", "type": "marketing"}, "html": UNSUBSCRIBE_HTML},
                "required",
            ),
        ]
    )
    def test_refuses_a_code_send_in_a_category_it_cant_send_in(
        self, cdp_post, _flag, capture, _name, make_category, fields, expected_code
    ):
        self._use_fakes(cdp_post, capture)
        if make_category:
            make_category(self)
        categories_before = set(
            MessageCategory.objects.filter(team=self.team).values_list("key", "category_type", "deleted")
        )
        keys_before = set(TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).values_list("key"))
        workflows_before = HogFlow.objects.filter(team=self.team).count()

        with patch.object(send_categories, "SEND_CATEGORY_LIMIT", 1):
            response = self._psak_client(["transactional_email:write"]).post(
                self.send_email_url, self._code_send(**fields), format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == expected_code
        assert self.cdp.received == []
        assert (
            set(MessageCategory.objects.filter(team=self.team).values_list("key", "category_type", "deleted"))
            == categories_before
        )
        assert (
            set(TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).values_list("key")) == keys_before
        )
        assert HogFlow.objects.filter(team=self.team).count() == workflows_before
        assert [send["error_code"] for send in self.events.properties("transactional email api send")] == [
            expected_code
        ]

    @parameterized.expand(
        [
            ("code_send_link", "code", {}, (400, "unsubscribe_link_required")),
            ("code_send_copies", "code", {}, (400, "copies_not_allowed")),
            ("code_send_with_files_link", "code", {"attachments": TWO_FILES}, (400, "unsubscribe_link_required")),
            ("code_send_with_files_copies", "code", {"attachments": TWO_FILES}, (400, "copies_not_allowed")),
            ("code_send_with_files_opted_out", "code", {"attachments": TWO_FILES}, (422, "recipient_opted_out")),
            ("template_send_link", "template", {}, (400, "unsubscribe_link_required")),
            ("template_send_copies", "template", {}, (400, "copies_not_allowed")),
            ("template_send_opted_out", "template", {}, (422, "recipient_opted_out")),
        ]
    )
    def test_the_email_pipelines_refusal_reaches_the_caller(
        self, cdp_post, _flag, capture, _name, form, fields, refusal
    ):
        self.cdp = self.enterContext(FakeCdpApi(refusal=refusal).serving(cdp_post))
        client = self._psak_client(["transactional_email:write"])

        if form == "code":
            response = client.post(
                self.send_email_url,
                self._code_send(category=self.NEWSLETTER, html=self.UNSUBSCRIBE_HTML, **fields),
                format="json",
            )
        else:
            response = client.post(self.url, self.body, format="json")

        assert (response.status_code, response.json()["code"]) == refusal

    def test_a_category_another_project_owns_is_not_this_projects(self, cdp_post, _flag, capture):
        self._use_fakes(cdp_post, capture)
        theirs = MessageCategory.objects.create(
            team=self._other_team_template().team, key="newsletter", name="Newsletter", category_type="transactional"
        )

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url, self._code_send(category=self.NEWSLETTER, html=self.UNSUBSCRIBE_HTML), format="json"
        )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        ours = MessageCategory.objects.get(team=self.team, key="newsletter")
        assert ours.id != theirs.id
        assert self.cdp.categories() == [{"id": str(ours.id), "type": "marketing"}]

    @parameterized.expand(
        [
            ("code_send_with_a_category", "code", NEWSLETTER, "categories_not_enabled"),
            ("template_send_with_a_category", "template", NEWSLETTER, "categories_not_enabled"),
            ("code_send_named_transactional", "code", "transactional", None),
            ("code_send_under_a_categorized_templates_key", "template_key", None, None),
            ("transactional_under_a_categorized_templates_key", "template_key", "transactional", "category_mismatch"),
        ]
    )
    def test_with_the_categories_flag_off_a_send_carries_no_category(
        self, cdp_post, flag, capture, _name, form, category, refusal
    ):
        self._use_fakes(cdp_post, capture)
        flag.side_effect = lambda key, *_args, **_kwargs: key != CODE_SEND_CATEGORIES_FLAG

        if form == "code":
            response = self.client.post(
                self.send_email_url, self._code_send(category=category, html=self.UNSUBSCRIBE_HTML), format="json"
            )
        elif form == "template_key":
            receipts = self._category(key="receipts", name="Receipts", category_type=MessageCategoryType.TRANSACTIONAL)
            MessageTemplate.objects.filter(id=self.template.id).update(key="password-reset", message_category=receipts)
            response = self.client.post(
                self.send_email_url,
                self._code_send(template_key="password-reset", **({"category": category} if category else {})),
                format="json",
            )
        else:
            response = self.client.post(self.url, {**self.body, "category": category}, format="json")

        if refusal is None:
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert (response.json()["code"], response.json()["attr"]) == (refusal, "category")
        assert not MessageCategory.objects.filter(team=self.team, key="newsletter").exists()
        assert self.cdp.categories() == ([None] if refusal is None else [])

    @parameterized.expand(
        [
            ("no_category_left_out", None, "template", {}, None),
            ("no_category_transactional", None, "template", {"category": "transactional"}, None),
            ("no_category_object", None, "send_email", {"category": NEWSLETTER}, "category_mismatch"),
            ("own_category_left_out", "receipts", "template", {}, "receipts"),
            (
                "own_category_renamed_does_not_rename_it",
                "receipts",
                "send_email",
                {"category": {"key": "receipts", "type": "transactional", "name": "Renamed"}},
                "receipts",
            ),
            (
                "own_category_named_transactional",
                "receipts",
                "template",
                {"category": "transactional"},
                "category_mismatch",
            ),
            (
                "own_category_other_key",
                "receipts",
                "send_email",
                {"category": {"key": "orders", "type": "transactional", "name": "Orders"}},
                "category_mismatch",
            ),
        ]
    )
    def test_a_template_send_follows_its_templates_category(
        self, cdp_post, _flag, capture, _name, template_category, route, fields, expected
    ):
        self._use_fakes(cdp_post, capture)
        if template_category:
            own = self._category(
                key=template_category, name="Receipts", category_type=MessageCategoryType.TRANSACTIONAL
            )
            MessageTemplate.objects.filter(id=self.template.id).update(message_category=own)

        response = self._send(self._psak_client(["transactional_email:write"]), route, {**self.body, **fields})

        if expected == "category_mismatch":
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert (response.json()["code"], response.json()["attr"]) == ("category_mismatch", "category")
            assert self.cdp.received == []
        else:
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
            assert len(self.cdp.categories()) == 1
        assert set(MessageCategory.objects.filter(team=self.team).values_list("key", "name")) == (
            {("receipts", "Receipts")} if template_category else set()
        )

    @parameterized.expand(
        [
            ("left_out", {}, status.HTTP_202_ACCEPTED),
            (
                "own_category",
                {"category": {"key": "receipts", "type": "transactional", "name": "Receipts"}},
                status.HTTP_202_ACCEPTED,
            ),
            ("another_category", {"category": NEWSLETTER, "html": UNSUBSCRIBE_HTML}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_a_code_send_under_a_templates_key_follows_the_templates_category(
        self, cdp_post, _flag, capture, _name, fields, expected_status
    ):
        self._use_fakes(cdp_post, capture)
        own = self._category(key="receipts", name="Receipts", category_type=MessageCategoryType.TRANSACTIONAL)
        MessageTemplate.objects.filter(id=self.template.id).update(key="password-reset", message_category=own)

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url, self._code_send(template_key="password-reset", **fields), format="json"
        )

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_202_ACCEPTED:
            assert self.cdp.categories() == [{"id": str(own.id), "type": "transactional"}]
        else:
            assert response.json()["code"] == "category_mismatch"
            assert self.cdp.received == []
        assert not MessageCategory.objects.filter(team=self.team, key="newsletter").exists()

    @parameterized.expand(
        [
            ("opted_out_of_the_category", "newsletter", NEWSLETTER, "recipient_opted_out"),
            ("opted_out_of_all_marketing", None, NEWSLETTER, "recipient_opted_out"),
            ("opted_out_of_another_category", "promos", NEWSLETTER, None),
            ("transactional_send_to_someone_opted_out_of_all_marketing", None, "transactional", None),
        ]
    )
    def test_a_marketing_code_send_skips_a_recipient_who_opted_out(
        self, cdp_post, _flag, capture, _name, opted_out_of, category, expected_code
    ):
        self._use_fakes(cdp_post, capture)
        self._category()
        self._category(key="promos", name="Promos")
        opted_out = self.client.post(
            f"/api/environments/{self.team.id}/messaging_preferences/add_opt_out/",
            {"identifier": "user@example.com", **({"category_key": opted_out_of} if opted_out_of else {})},
            format="json",
        )
        assert opted_out.status_code == status.HTTP_201_CREATED, opted_out.json()

        response = self._psak_client(["transactional_email:write"]).post(
            self.send_email_url, self._code_send(category=category, html=self.UNSUBSCRIBE_HTML), format="json"
        )

        if expected_code:
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.json()
            assert response.json()["code"] == expected_code
            assert self.cdp.emails() == []
        else:
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
            assert len(self.cdp.emails()) == 1

    def test_a_form_encoded_code_send_without_capture_engagement_captures_engagement(self, mock_post, _flag, _capture):
        with FakeCdpApi().serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(), format="multipart"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert cdp.deliver() == [("$workflows_email_sent", "user-1")]

    @parameterized.expand(
        [
            ("no_subject", {"subject": ""}, "subject"),
            ("no_body", {"html": None}, "html"),
            ("data_for_rendered_content", {"message_data": {"name": "Jane"}}, "message_data"),
            ("both_a_template_and_a_key", {"template_id": str(uuid4())}, "template_id"),
            ("both_a_nested_template_and_a_key", {"template": {"id": str(uuid4())}}, "template_id"),
            ("neither_a_template_nor_a_key", {"template_key": None}, "template_id"),
            ("nested_identifiers", {"identifiers": {"distinct_id": "user-1"}}, "identifiers"),
            ("invalid_key", {"template_key": "welcome email"}, "template_key"),
            ("key_over_256_characters", {"template_key": "k" * 257}, "template_key"),
            ("sender_that_is_not_an_address", {"from": "Example"}, "from"),
            ("sender_with_a_quoted_local_part", {"from": '"security"@example.com'}, "from"),
            ("sender_nested_too_deep_to_parse", {"from": "(" * 1000 + "security@example.com" + ")" * 1000}, "from"),
            ("sender_over_1024_characters", {"from": "E" * 1024 + " <security@example.com>"}, "from"),
            ("empty_reply_to", {"reply_to": []}, "reply_to"),
            (
                "liquid_in_a_copy_address",
                {"bcc": ["audit@example.com", "{{person.properties.email}}@example.com"]},
                None,
            ),
            ("field_this_server_lacks", {"scheduled_at": "2026-11-01T09:00:00Z"}, "scheduled_at"),
            ("empty_key_beside_a_field_this_server_lacks", {"": "", "scheduled_at": "2026-11-01T09:00:00Z"}, None),
            ("html_over_5_mib_in_utf8", {"html": "é" * (5 * 1024 * 1024 // 2 + 1)}, "html"),
            ("text_over_5_mib_in_utf8", {"text": "é" * (5 * 1024 * 1024 // 2 + 1)}, "text"),
        ]
    )
    def test_refuses_a_code_send_with_an_invalid_field(self, mock_post, _flag, _capture, _name, fields, attr):
        body = {key: value for key, value in self._code_send(**fields).items() if value is not None}

        with FakeCdpApi().serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(self.send_email_url, body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == attr
        assert cdp.received == []

    @parameterized.expand(
        [
            ("to", "jane=tag@example.com", True),
            ("to", "jane@localhost", False),
            ("reply_to", "jane=tag@example.com", True),
            ("reply_to", "jane@localhost", False),
        ]
    )
    def test_a_code_send_takes_the_addresses_the_pipeline_takes(
        self, mock_post, _flag, _capture, field, address, accepted
    ):
        self._cdp_accepts(mock_post)
        value = address if field == "to" else [address]

        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, self._code_send(**{field: value}), format="json"
        )

        if accepted:
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
            sent = json.loads(mock_post.call_args.kwargs["data"])
            assert (sent["to"] if field == "to" else sent["send"]["replyTo"]) == value
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert response.json()["attr"].startswith(field)
            mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("subject", "Hi", "validation_error"),
            ("cc", "copy@example.com", "invalid_request"),
            ("bcc", ["audit@example.com"], "invalid_request"),
            ("attachments", TWO_FILES[:1], "invalid_request"),
        ]
    )
    def test_refuses_code_fields_on_a_template_send(self, mock_post, _flag, _capture, field, value, error_type):
        response = self._send(self._psak_client(["hog_flow:write"]), "send_email", {**self.body, field: value})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["attr"], response.json()["type"]) == (field, error_type)
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            ("nulls", {"cc": None, "bcc": None, "attachments": None}),
        ]
    )
    def test_takes_empty_copies_and_attachments_on_a_template_send(self, mock_post, _flag, _capture, _name, fields):
        self._cdp_accepts(mock_post)

        response = self._send(self._psak_client(["hog_flow:write"]), "send_email", {**self.body, **fields})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        mock_post.assert_called_once()

    def test_a_file_sent_inline_is_refused_without_repeating_its_content(self, mock_post, _flag, _capture):
        attachments = [{"sha256": CSV, "filename": "invoice.pdf", "content": "c2VjcmV0LWludm9pY2UtYnl0ZXM="}]

        with FakeCdpApi().serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(attachments=attachments), format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        body = response.json()
        assert (body["type"], body["code"], body["attr"]) == (
            "invalid_request",
            "invalid_request",
            "attachments__0__content",
        )
        assert "uploaded files" in body["why"]
        assert "messaging/attachments/uploads/" in body["fix"]
        assert "c2VjcmV0" not in response.content.decode()
        assert cdp.emails() == []

    @parameterized.expand(
        [
            (
                "a_header_too_long",
                {"attachments": [{"sha256": CSV, "filename": "logo.png", "content_id": "x" * 79}]},
                "attachments__0__content_id",
                "Shorten `content_id` to 78 characters",
            ),
            ("too_many_copies", {"bcc": [f"user{i}@example.com" for i in range(11)]}, "bcc", "at most 10 addresses"),
            (
                "an_attachment_that_is_not_an_object",
                {"attachments": ["logo.png"]},
                "attachments__0",
                "`{sha256, filename}`",
            ),
        ]
    )
    def test_a_refused_extra_field_names_its_remedy(self, mock_post, _flag, _capture, _name, fields, attr, fix):
        with FakeCdpApi().serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(**fields), format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["code"], response.json()["attr"]) == ("invalid_request", attr)
        assert fix in response.json()["fix"]
        assert cdp.emails() == []

    @parameterized.expand(
        [
            ("the_only_verified_sender", ["verified"], status.HTTP_202_ACCEPTED, None),
            (
                "one_of_several_verified_senders",
                ["verified", "verified"],
                status.HTTP_400_BAD_REQUEST,
                "sender_required",
            ),
            ("no_verified_sender", ["unverified"], status.HTTP_400_BAD_REQUEST, "sender_not_verified"),
        ]
    )
    def test_a_code_send_without_from_and_without_a_default_sends_from(
        self, mock_post, _flag, _capture, _name, senders, expected_status, code
    ):
        self._cdp_accepts(mock_post)
        Integration.objects.filter(id=self.sender.id).delete()
        TeamWorkflowsConfig.objects.filter(team_id=self.team.id).update(default_email_integration_id=None)
        created = [
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=f"sender-{index}@example.com",
                config={"verified": state == "verified"},
            )
            for index, state in enumerate(senders)
        ]

        response = self._psak_client(["hog_flow:write"]).post(self.send_email_url, self._code_send(), format="json")

        assert response.status_code == expected_status, response.json()
        if code is None:
            assert json.loads(mock_post.call_args.kwargs["data"])["send"]["from"] == {"integrationId": created[0].id}
        else:
            assert (response.json()["type"], response.json()["code"], response.json()["attr"]) == (
                "invalid_request",
                code,
                None,
            )
            mock_post.assert_not_called()

    def test_refuses_a_code_send_from_an_unverified_domain(self, mock_post, _flag, capture):
        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, self._code_send(**{"from": "security@example.org"}), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert (response.json()["type"], response.json()["code"], response.json()["attr"]) == (
            "invalid_request",
            "sender_not_verified",
            "from",
        )
        assert not TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).exists()
        assert capture.call_args.kwargs["properties"]["error_code"] == "sender_not_verified"
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("timeout", {}, {"side_effect": requests.ReadTimeout()}),
            (
                "file_storage_down",
                {"attachments": TWO_FILES},
                {"return_value": MagicMock(status_code=503, json=lambda: {"error": "delivery_unavailable"})},
            ),
        ]
    )
    def test_a_code_send_the_pipeline_does_not_confirm_warns_it_may_still_go_out(
        self, mock_post, _flag, _capture, _name, fields, pipeline
    ):
        mock_post.configure_mock(**pipeline)

        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, self._code_send(**fields), format="json"
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "delivery_unavailable"
        assert "may still go out" in response.json()["detail"]
        assert "within 24 hours with the same Idempotency-Key" in response.json()["detail"]
        assert "same `Idempotency-Key`" in response.json()["fix"]

    def test_the_send_schema_gives_a_template_send_no_code_only_field(self, _mock_post, _flag, _capture):
        schema = self.client.get("/api/schema/").data

        send_email = schema["paths"]["/api/projects/{project_id}/messaging/send/email/"]["post"]
        reference = send_email["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        fields = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]["properties"]
        assert {name: fields[name]["default"] for name in CODE_SEND_FIELDS if "default" in fields[name]} == {}

    def test_a_code_send_passes_its_idempotency_key_and_reports_a_replay(self, mock_post, _flag, _capture):
        mock_post.return_value = MagicMock(
            status_code=202, json=lambda: {"invocation_id": "first-send", "replayed": True}
        )

        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, self._code_send(), format="json", headers={"Idempotency-Key": "welcome:user-1"}
        )

        assert response.status_code == 202, response.json()
        assert json.loads(mock_post.call_args.kwargs["data"])["idempotency_key"] == "welcome:user-1"
        assert response.json() == {"message_id": "first-send", "replayed": True}

    def test_a_code_send_an_older_pipeline_does_not_take_is_refused_on_that_field(self, mock_post, _flag, capture):
        events = CapturedEvents(capture)

        with FakeCdpApi(takes_attachments=False).serving(mock_post) as cdp:
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(attachments=TWO_FILES), format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        body = response.json()
        assert (body["code"], body["attr"]) == ("field_not_accepted", "attachments")
        assert "doesn't take the field yet" in body["why"]
        assert "Send the email without this field" in body["fix"]
        assert cdp.emails() == []
        assert [payload["send"]["attachments"] for payload in cdp.received] == [TWO_FILES]
        assert [
            (sent["outcome"], sent["error_code"], sent["attachment_count"], sent["attachment_bytes"])
            for sent in events.properties("transactional email api send")
        ] == [("rejected", "field_not_accepted", 2, None)]

    @parameterized.expand(
        [
            (
                "not_uploaded",
                400,
                {"error": "attachment_not_uploaded", "sha256": NOTES},
                "attachment_not_uploaded",
                "attachments__1__sha256",
                "messaging/attachments/uploads/",
            ),
            (
                "too_large",
                400,
                {"error": "message_too_large", "sha256": CSV, "attachment_bytes": 30_000_000},
                "message_too_large",
                "attachments__0__sha256",
                "40 MB after Base64 encoding, about 29 MB of files",
            ),
            (
                "too_large_answered_as_a_payload_too_large",
                413,
                {"error": "message_too_large", "sha256": CSV},
                "message_too_large",
                "attachments__0__sha256",
                "40 MB after Base64 encoding, about 29 MB of files",
            ),
            (
                "too_large_naming_no_file_it_was_sent",
                400,
                {"error": "message_too_large"},
                "message_too_large",
                "attachments",
                "40 MB after Base64 encoding, about 29 MB of files",
            ),
            (
                "files_off_for_this_project",
                400,
                {"error": "field_not_accepted"},
                "field_not_accepted",
                "attachments",
                "without this field",
            ),
            (
                "a_workflow_that_can_wait",
                400,
                {"error": "workflow_can_wait", "reason": "A step can hold the send.", "fix": "Drop the delay."},
                "workflow_can_wait",
                "attachments",
                "Drop the delay.",
            ),
            (
                "a_workflow_that_can_wait_explained_by_posthog",
                400,
                {"error": "workflow_can_wait"},
                "workflow_can_wait",
                "attachments",
                "without files",
            ),
            (
                "a_workflow_shape_that_cannot_send_files",
                400,
                {"error": "workflow_shape_not_supported", "reason": "It branches.", "fix": "Use one email step."},
                "workflow_shape_not_supported",
                "attachments",
                "Use one email step.",
            ),
            (
                "a_template_too_heavy_to_measure",
                400,
                {"error": "email_render_limit_exceeded", "reason": "It ran too long.", "fix": "Simplify it."},
                "email_render_limit_exceeded",
                "attachments",
                "Simplify it.",
            ),
            (
                "a_utm_value_too_long_to_measure",
                400,
                {"error": "utm_value_too_long", "reason": "The campaign value is long.", "fix": "Shorten it."},
                "utm_value_too_long",
                "attachments",
                "Shorten it.",
            ),
            (
                "a_template_with_too_many_tags_explained_by_posthog",
                400,
                {"error": "email_body_too_many_tags"},
                "email_body_too_many_tags",
                "attachments",
                "10,000 Liquid tags or fewer",
            ),
        ]
    )
    def test_a_file_the_pipeline_refuses_is_named_with_a_reason_and_a_fix(
        self, mock_post, _flag, _capture, _name, pipeline_status, pipeline_body, code, attr, fix
    ):
        mock_post.return_value = MagicMock(status_code=pipeline_status, json=lambda: pipeline_body)

        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, self._code_send(attachments=TWO_FILES), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        body = response.json()
        assert (body["type"], body["code"], body["attr"]) == ("invalid_request", code, attr)
        assert body["why"] == pipeline_body.get("reason", body["why"]) and body["why"]
        assert fix in body["fix"]

    @parameterized.expand(
        [
            (
                "queued",
                "code",
                {"attachments": TWO_FILES},
                {
                    "return_value": MagicMock(
                        status_code=202, json=lambda: {"invocation_id": "i", "attachment_bytes": 5}
                    )
                },
                202,
                ("queued", None, 2, 5),
            ),
            (
                "queued_without_the_size_of_its_files",
                "code",
                {"attachments": TWO_FILES},
                CDP_ACCEPTS,
                202,
                ("queued", None, 2, None),
            ),
            ("replayed", "code", {}, {"return_value": CDP_REPLAYS}, 202, ("replayed", None, 0, 0)),
            (
                "refused_by_the_pipeline",
                "code",
                {"attachments": TWO_FILES},
                {
                    "return_value": MagicMock(
                        status_code=422, json=lambda: {"error": "recipient_suppressed", "attachment_bytes": 5}
                    )
                },
                422,
                ("rejected", "recipient_suppressed", 2, 5),
            ),
            (
                "a_file_not_uploaded",
                "code",
                {"attachments": TWO_FILES},
                {
                    "return_value": MagicMock(
                        status_code=400, json=lambda: {"error": "attachment_not_uploaded", "sha256": NOTES}
                    )
                },
                400,
                ("rejected", "attachment_not_uploaded", 2, None),
            ),
            (
                "files_too_large_for_one_email",
                "code",
                {"attachments": TWO_FILES},
                {
                    "return_value": MagicMock(
                        status_code=400,
                        json=lambda: {"error": "message_too_large", "sha256": CSV, "attachment_bytes": 30_000_000},
                    )
                },
                400,
                ("rejected", "message_too_large", 2, 30_000_000),
            ),
            (
                "pipeline_unavailable",
                "code",
                {"attachments": TWO_FILES},
                {"side_effect": requests.ReadTimeout()},
                503,
                ("unavailable", None, 2, None),
            ),
            (
                "too_many_attachments",
                "code",
                {"attachments": TWO_FILES[:1] * 11},
                CDP_ACCEPTS,
                400,
                ("rejected", "max_length", 11, None),
            ),
            (
                "a_blocked_file_type",
                "code",
                {"attachments": [{"sha256": CSV, "filename": "setup.exe"}]},
                CDP_ACCEPTS,
                400,
                ("rejected", "blocked_file_type", 1, None),
            ),
            ("template_send", "template", {}, CDP_ACCEPTS, 202, ("queued", None, 0, 0)),
            (
                "template_send_to_an_invalid_recipient",
                "template",
                {"to": "not an address"},
                CDP_ACCEPTS,
                400,
                ("rejected", "invalid_input", 0, 0),
            ),
        ]
    )
    def test_reports_the_attachments_of_every_send_outcome(
        self, mock_post, _flag, capture, _name, route, fields, pipeline, expected_status, expected
    ):
        mock_post.configure_mock(**pipeline)

        if route == "code":
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url, self._code_send(**fields), format="json"
            )
        else:
            response = self.client.post(self.url, {**self.body, **fields}, format="json")

        assert response.status_code == expected_status, response.json()
        reported = [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs.get("event") == "transactional email api send"
        ]
        assert [
            (
                properties["route"],
                properties.get("addressed_by"),
                properties["outcome"],
                properties.get("error_code"),
                properties["attachment_count"],
                properties["attachment_bytes"],
            )
            for properties in reported
        ] == [("send_email" if route == "code" else "template", "template_key" if route == "code" else None, *expected)]

    @parameterized.expand([("code_send", "code"), ("template_send", "template")])
    def test_refuses_a_body_over_the_request_cap_and_reports_its_size_as_unknown(
        self, mock_post, _flag, capture, _name, route
    ):
        self._cdp_accepts(mock_post)
        over_the_cap = "x" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1)

        if route == "code":
            response = self._psak_client(["hog_flow:write"]).post(
                self.send_email_url,
                self._code_send(html=over_the_cap),
                format="json",
            )
        else:
            response = self.client.post(self.url, {**self.body, "message_data": {"blob": over_the_cap}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert (body["type"], body["code"]) == ("invalid_request", "content_too_large")
        assert body["why"] and body["fix"]
        mock_post.assert_not_called()
        reported = [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs.get("event") == "transactional email api send"
        ]
        assert [
            (
                properties["team_id"],
                properties["route"],
                properties["outcome"],
                properties["error_code"],
                properties["attachment_count"],
                properties["attachment_bytes"],
            )
            for properties in reported
        ] == [
            (self.team.id, "send_email" if route == "code" else "template", "rejected", "content_too_large", None, None)
        ]

    def test_a_body_over_the_request_cap_from_a_key_of_another_project_is_denied(self, mock_post, _flag, capture):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        over_the_cap = "x" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1)

        response = self._psak_client(["hog_flow:write"], team=other_team).post(
            self.send_email_url,
            self._code_send(html=over_the_cap),
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert [
            call for call in capture.call_args_list if call.kwargs.get("event") == "transactional email api send"
        ] == []

    @parameterized.expand(
        [
            ("accepted_without_files", {}, 202, (0, 0)),
            (
                "refused_with_files",
                {"attachments[0]filename": "notes.txt", "attachments[0]sha256": NOTES},
                400,
                (None, None),
            ),
        ]
    )
    def test_reports_the_attachments_of_a_send_in_a_form_body(
        self, mock_post, _flag, capture, _name, fields, expected_status, expected
    ):
        mock_post.configure_mock(**CDP_ACCEPTS)

        response = self._psak_client(["hog_flow:write"]).post(
            self.send_email_url, {**self._code_send(), **fields}, format="multipart"
        )

        assert response.status_code == expected_status, response.json()
        assert [
            (call.kwargs["properties"]["attachment_count"], call.kwargs["properties"]["attachment_bytes"])
            for call in capture.call_args_list
            if call.kwargs.get("event") == "transactional email api send"
        ] == [expected]

    @parameterized.expand(
        [
            ("below_the_key_limit", transactional_email.TRANSACTIONAL_EMAIL_KEY_LIMIT),
            ("winner_takes_the_last_key", 1),
        ]
    )
    def test_two_racing_first_sends_of_a_key_make_one_workflow(self, mock_post, _flag, _capture, _name, key_limit):
        self._cdp_accepts(mock_post)
        psak = self._psak_client(["hog_flow:write"])
        lookup = transactional_email.known_key
        lookups: list[str] = []

        def misses_the_winner_once(team_id: int, key: str) -> TransactionalEmailKey | None:
            lookups.append(key)
            return None if len(lookups) == 1 else lookup(team_id, key)

        with patch.object(transactional_email, "TRANSACTIONAL_EMAIL_KEY_LIMIT", key_limit):
            winner = psak.post(self.send_email_url, self._code_send(), format="json")
            with patch.object(transactional_email, "known_key", side_effect=misses_the_winner_once):
                loser = psak.post(self.send_email_url, self._code_send(), format="json")

        assert (winner.status_code, loser.status_code) == (status.HTTP_202_ACCEPTED, status.HTTP_202_ACCEPTED)
        first_url, second_url = (call.args[0] for call in mock_post.call_args_list)
        assert first_url == second_url
        assert TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(key="welcome").count() == 1
        assert HogFlow.objects.filter(team=self.team, name="welcome").count() == 1

    @parameterized.expand(
        [
            ("code_send_with_only_its_flag", "code", {EMAIL_FROM_CODE_FLAG}, status.HTTP_202_ACCEPTED),
            ("code_send_without_its_flag", "code", {TRANSACTIONAL_EMAIL_API_FLAG}, status.HTTP_404_NOT_FOUND),
            ("template_send_without_its_flag", "template", {EMAIL_FROM_CODE_FLAG}, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_each_form_of_a_send_answers_only_while_its_flag_is_on(
        self, mock_post, flag, _capture, _name, form, enabled_flags, expected_status
    ):
        self._cdp_accepts(mock_post)
        flag.side_effect = lambda key, *_args, **_kwargs: key in enabled_flags
        body = self._code_send() if form == "code" else self._flat(self.body)

        response = self.client.post(self.send_email_url, body, format="json")

        assert response.status_code == expected_status, response.json()
        assert mock_post.called == (expected_status == status.HTTP_202_ACCEPTED)

    def _other_team_template(self) -> MessageTemplate:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        template = MessageTemplate.objects.create(
            team=other_team,
            name="Other reset",
            content={"email": {"subject": "Reset", "html": "<p>Reset</p>"}},
            type="email",
        )
        sender = Integration.objects.create(
            team=other_team, kind="email", integration_id="other@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(other_team.id, sender.id)
        make_transactional(other_team.id, template.id, user_id=self.user.id, from_integration_id=None)
        return template

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

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
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
            reload.assert_not_called()

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

    def _sender_client(self, sender: str) -> APIClient:
        if sender == "personal_api_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="email", user=self.user, secure_value=hash_key_value(token), scopes=["transactional_email:write"]
            )
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            return client
        return self._psak_client(
            ["transactional_email:write"], created_by=self.user if sender == "key_creator" else None
        )

    @staticmethod
    def _first_code_sends(capture: MagicMock) -> list[CapturedFirstCodeSend]:
        return [
            CapturedFirstCodeSend(
                distinct_id=call.kwargs["distinct_id"],
                properties=call.kwargs["properties"],
                organization_id=call.kwargs["groups"]["organization"],
                project=call.kwargs["groups"]["project"],
            )
            for call in capture.call_args_list
            if call.kwargs["event"] == "email first code send"
        ]

    @parameterized.expand([("the_project", False), ("an_environment", True)])
    def test_the_first_code_send_of_a_project_is_reported_once_for_whoever_made_its_key_in(
        self, mock_post, _flag, capture, _name, in_environment
    ):
        self._cdp_accepts(mock_post)
        key_team = self.team
        if in_environment:
            key_team = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
            sender = Integration.objects.create(
                team=key_team, kind="email", integration_id="hello@example.com", config={"verified": True}
            )
            set_default_email_sender_if_unset(key_team.id, sender.id)
        psak = self._psak_client(["hog_flow:write"], created_by=self.user, team=key_team)
        url = f"/api/projects/{key_team.id}/messaging/send/email/"

        with self.captureOnCommitCallbacks(execute=True):
            first = psak.post(url, self._code_send(), format="json")
        with self.captureOnCommitCallbacks(execute=True):
            second = psak.post(url, self._code_send(), format="json")

        assert (first.status_code, second.status_code) == (status.HTTP_202_ACCEPTED, status.HTTP_202_ACCEPTED), (
            first.json()
        )
        assert self._first_code_sends(capture) == [
            CapturedFirstCodeSend(
                distinct_id=self.user.distinct_id,
                properties={"team_id": self.team.id, "addressed_by": "template_key"},
                organization_id=str(self.organization.id),
                project=str(self.team.uuid),
            )
        ]

    def test_a_template_send_by_id_counts_as_the_first_code_send(self, mock_post, _flag, capture):
        self._cdp_accepts(mock_post)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._send(self._sender_client("key_creator"), "send_email", self.body)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert [sent.properties["addressed_by"] for sent in self._first_code_sends(capture)] == ["template_id"]

    @parameterized.expand(
        [
            (
                "a_replay",
                "key_creator",
                MagicMock(status_code=202, json=lambda: {"invocation_id": "a", "replayed": True}),
                True,
                202,
            ),
            ("a_key_nobody_made", "key_without_creator", None, True, 202),
            ("a_personal_api_key", "personal_api_key", None, True, 202),
            ("a_send_the_pipeline_refuses", "key_creator", MagicMock(status_code=429), True, 503),
            ("the_flag_off", "key_creator", None, False, 404),
        ]
    )
    def test_reports_no_first_code_send_for(
        self, mock_post, flag, capture, _name, sender, pipeline_answer, flag_on, expected_status
    ):
        self._cdp_accepts(mock_post)
        if pipeline_answer is not None:
            mock_post.return_value = pipeline_answer
        flag.return_value = flag_on

        with self.captureOnCommitCallbacks(execute=True):
            response = self._sender_client(sender).post(self.send_email_url, self._code_send(), format="json")

        assert response.status_code == expected_status, response.json()
        assert self._first_code_sends(capture) == []

    @parameterized.expand(
        [
            ("raises", {"side_effect": RuntimeError("capture is down")}),
            ("drops_the_event", {"return_value": None}),
        ]
    )
    def test_a_first_code_send_that_fails_to_capture_leaves_it_to_a_later_send(
        self, mock_post, _flag, capture, _name, failure
    ):
        self._cdp_accepts(mock_post)
        psak = self._sender_client("key_creator")
        capture.configure_mock(**failure)

        with self.captureOnCommitCallbacks(execute=True):
            failed = psak.post(self.send_email_url, self._code_send(), format="json")
        capture.reset_mock(side_effect=True, return_value=True)
        with self.captureOnCommitCallbacks(execute=True):
            later = psak.post(self.send_email_url, self._code_send(), format="json")

        assert (failed.status_code, later.status_code) == (status.HTTP_202_ACCEPTED, status.HTTP_202_ACCEPTED)
        assert [sent.properties["addressed_by"] for sent in self._first_code_sends(capture)] == ["template_key"]

    @parameterized.expand(
        [
            ("the_template_route", "send", {EMAIL_FROM_CODE_FLAG, TRANSACTIONAL_EMAIL_API_FLAG}),
            ("send_email_without_the_code_flag", "send_email", {TRANSACTIONAL_EMAIL_API_FLAG}),
        ]
    )
    def test_a_template_send_by_id_reports_no_first_code_send_on(self, mock_post, flag, capture, _name, route, flags):
        self._cdp_accepts(mock_post)
        flag.side_effect = lambda name, *args, **kwargs: name in flags

        with self.captureOnCommitCallbacks(execute=True):
            response = self._send(self._sender_client("key_creator"), route, self.body)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert self._first_code_sends(capture) == []
        assert not FirstCodeSend.objects.for_team(self.team.id).exists()

    def test_a_creator_deleted_before_the_callback_leaves_the_first_code_send_to_a_later_send(
        self, mock_post, _flag, capture
    ):
        self._cdp_accepts(mock_post)
        departed = User.objects.create_and_join(self.organization, "departed@example.com", None)
        departed_psak = self._psak_client(["hog_flow:write"], created_by=departed, label="departed")

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            departed_psak.post(self.send_email_url, self._code_send(), format="json")
        departed.delete()
        for callback in callbacks:
            callback()
        with self.captureOnCommitCallbacks(execute=True):
            self._sender_client("key_creator").post(self.send_email_url, self._code_send(), format="json")

        assert self._first_code_sends(capture) == [
            CapturedFirstCodeSend(
                distinct_id=self.user.distinct_id,
                properties={"team_id": self.team.id, "addressed_by": "template_key"},
                organization_id=str(self.organization.id),
                project=str(self.team.uuid),
            )
        ]

    def test_a_later_code_send_makes_no_first_code_send_insert(self, mock_post, _flag, _capture):
        self._cdp_accepts(mock_post)
        psak = self._sender_client("key_creator")
        with self.captureOnCommitCallbacks(execute=True):
            psak.post(self.send_email_url, self._code_send(), format="json")

        with CaptureQueriesContext(connection) as queries, self.captureOnCommitCallbacks(execute=True):
            response = psak.post(self.send_email_url, self._code_send(), format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert [
            query["sql"]
            for query in queries.captured_queries
            if 'INSERT INTO "messaging_firstcodesend"' in query["sql"]
        ] == []

    def test_reports_a_projects_first_code_send_once(self, _mock_post, _flag, _capture):
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        other_team = Team.objects.create(organization=self.organization)
        captured: list[int] = []

        def capture_for(team_id: int) -> Callable[[], bool]:
            def capture() -> bool:
                captured.append(team_id)
                return True

            return capture

        for team_id in (self.team.id, self.team.id, environment.id, other_team.id):
            report_first_code_send(team_id, capture_for(team_id))

        assert captured == [self.team.id, other_team.id]


@pytest.mark.ee
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
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
            ("send", "post", "send/", {"to": "user@example.com"}),
            ("update", "patch", "", {"content": {"email": {"subject": "New", "html": "<p>New</p>"}}}),
            ("save_draft", "patch", "", {"draft_content": {"email": {"subject": "Draft", "html": "<p>Draft</p>"}}}),
        ]
    )
    def test_a_member_denied_the_workflow_cannot_send_or_change_it(self, mock_post, _flag, _name, method, suffix, body):
        url = f"/api/projects/{self.team.id}/messaging_templates/{self.template.id}/{suffix}"

        response = getattr(self.client, method)(url, body, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    def test_a_member_denied_the_workflow_cannot_send_code_under_its_template_key(self, mock_post, _flag):
        MessageTemplate.objects.filter(id=self.template.id).update(key="password-reset")

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {"to": "user@example.com", "template_key": "password-reset", "subject": "Hi", "html": "<p>Hi</p>"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_post.assert_not_called()

    def test_a_member_who_cannot_create_workflows_cannot_send_code_under_a_new_key(self, mock_post, _flag):
        self._login_member("viewer@example.com", {None: "viewer", str(self.hog_flow_id): "editor"})
        workflows_before = HogFlow.objects.filter(team=self.team).count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {"to": "user@example.com", "template_key": "welcome", "subject": "Welcome", "html": "<p>Hi</p>"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert HogFlow.objects.filter(team=self.team).count() == workflows_before
        assert not TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).exists()
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("no_category", True, {}, status.HTTP_202_ACCEPTED),
            ("category_object", True, MARKETING_SEND, status.HTTP_403_FORBIDDEN),
            ("category_object_with_categories_off", False, MARKETING_SEND, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_editor_access_to_a_keys_workflow_cannot_create_categories(
        self, cdp_post, flag, _name, categories_on, fields, expected_status
    ):
        flag.side_effect = lambda key, *_args, **_kwargs: categories_on or key != CODE_SEND_CATEGORIES_FLAG
        cdp = self.enterContext(FakeCdpApi().serving(cdp_post))
        hog_flow_id = transactional_email._key_workflow_id(self.team.id, "weekly")
        self._login_member("viewer@example.com", {None: "viewer", str(hog_flow_id): "editor"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {"to": "user@example.com", "template_key": "weekly", "subject": "Weekly", "html": "<p>Hi</p>", **fields},
            format="json",
        )

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert response.json()["code"] == "categories_not_enabled"
        assert not MessageCategory.objects.filter(team=self.team).exists()
        assert len(cdp.emails()) == (1 if expected_status == status.HTTP_202_ACCEPTED else 0)

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


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestSendCategoryCreatedConcurrently(NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="transactional email",
            secure_value=hash_key_value(raw_token),
            scopes=["transactional_email:write"],
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")

    def _insert_and_commit_once_the_send_waits(self, inserted: threading.Event, app: dict[str, Any]) -> None:
        try:
            with transaction.atomic():
                app["category_id"] = MessageCategory.objects.create(
                    team=self.team, key="newsletter", name="Made in the app", category_type="marketing"
                ).id
                inserted.set()
                app["send_waited"] = self._send_waits_on_the_insert()
        except Exception as error:
            app["error"] = error
        finally:
            inserted.set()
            connection.close()

    def _send_waits_on_the_insert(self) -> bool:
        try:
            wait_until(self._send_is_waiting_on_the_insert, timeout=30, interval=0.05)
        except AssertionError:
            return False
        return True

    def _send_is_waiting_on_the_insert(self) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND query ILIKE 'INSERT INTO \"posthog_messagecategory\"%%'"
            )
            return bool(cursor.fetchone()[0])

    def _restore_and_commit_once_the_send_waits(
        self, category_id: Any, restored: threading.Event, other: dict[str, Any]
    ) -> None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        [f"{send_categories.SEND_CATEGORY_LOCK}:{self.team.id}"],
                    )
                MessageCategory.objects.filter(id=category_id).update(deleted=False)
                restored.set()
                other["send_waited"] = self._send_waits(self._send_is_waiting_on_a_lock)
        except Exception as error:
            other["error"] = error
        finally:
            restored.set()
            connection.close()

    def _send_waits(self, waiting: Callable[[], bool]) -> bool:
        try:
            wait_until(waiting, timeout=30, interval=0.05)
        except AssertionError:
            return False
        return True

    def _send_is_waiting_on_a_lock(self) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
            return bool(cursor.fetchone()[0])

    def test_a_category_another_send_restores_at_the_limit_is_used(self, cdp_post, _flag, _capture):
        cdp = self.enterContext(FakeCdpApi().serving(cdp_post))
        archived = MessageCategory.objects.create(
            team=self.team, key="newsletter", name="Newsletter", category_type="marketing", deleted=True
        )
        restored = threading.Event()
        other: dict[str, Any] = {}
        worker = threading.Thread(
            target=self._restore_and_commit_once_the_send_waits, args=(archived.id, restored, other)
        )
        worker.start()
        assert restored.wait(timeout=30)

        with patch.object(send_categories, "SEND_CATEGORY_LIMIT", 1):
            response = self.client.post(
                f"/api/projects/{self.team.id}/messaging/send/email/",
                {
                    "to": "user@example.com",
                    "template_key": "welcome",
                    "subject": "Welcome",
                    "html": '<a href="{{ unsubscribe_url }}">Unsubscribe</a>',
                    "category": {"key": "newsletter", "type": "marketing", "name": "Newsletter"},
                },
                format="json",
            )
        worker.join(timeout=30)

        assert not worker.is_alive()
        assert "error" not in other, other.get("error")
        assert other["send_waited"], "the send never waited on the other restore, so the two did not race"
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert cdp.categories() == [{"id": str(archived.id), "type": "marketing"}]

    def test_a_key_the_app_creates_while_the_send_inserts_it_is_the_one_used(self, cdp_post, _flag, _capture):
        cdp = self.enterContext(FakeCdpApi().serving(cdp_post))
        inserted = threading.Event()
        app: dict[str, Any] = {}
        worker = threading.Thread(target=self._insert_and_commit_once_the_send_waits, args=(inserted, app))
        worker.start()
        assert inserted.wait(timeout=30)

        response = self.client.post(
            f"/api/projects/{self.team.id}/messaging/send/email/",
            {
                "to": "user@example.com",
                "template_key": "welcome",
                "subject": "Welcome",
                "html": '<a href="{{ unsubscribe_url }}">Unsubscribe</a>',
                "category": {"key": "newsletter", "type": "marketing", "name": "Newsletter"},
            },
            format="json",
        )
        worker.join(timeout=30)

        assert not worker.is_alive()
        assert "error" not in app, app.get("error")
        assert app["send_waited"], "the send never waited on the app's insert, so the two did not race"
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert cdp.categories() == [{"id": str(app["category_id"]), "type": "marketing"}]
        assert MessageCategory.objects.filter(team=self.team, key="newsletter").count() == 1
