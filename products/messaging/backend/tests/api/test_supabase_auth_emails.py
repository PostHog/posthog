import hmac
import json
import time
import base64
import hashlib
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.models import MessageTemplate, SupabaseAuthEmailConfig
from products.messaging.backend.services.design_validation import validate_design
from products.messaging.backend.services.supabase_auth_emails import SEND_BUDGET_SECONDS
from products.messaging.backend.services.transactional_email import make_transactional
from products.workflows.backend.facade.api import set_default_email_sender_if_unset

SIGNING_KEY = b"k" * 32
HOOK_SECRET = "v1,whsec_" + base64.b64encode(SIGNING_KEY).decode()


def _signed_headers(
    body: bytes, *, webhook_id: str = "msg_1", key: bytes = SIGNING_KEY, signing_keys: list[bytes] | None = None
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed = f"{webhook_id}.{timestamp}.".encode() + body
    signatures = [
        "v1," + base64.b64encode(hmac.new(k, signed, hashlib.sha256).digest()).decode() for k in (signing_keys or [key])
    ]
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        # Supabase joins the signatures with ", ".
        "webhook-signature": ", ".join(signatures),
    }


REQUEST_ID = "5f0e7a52-0000-4000-8000-000000000002"


def _payload(action: str, user_email: str = "current@example.com", **email_data: str) -> dict[str, Any]:
    return {
        "metadata": {"uuid": REQUEST_ID, "name": "send-email"},
        "user": {
            "id": "8d0c0b6e-0000-4000-8000-000000000001",
            "email": user_email,
            "new_email": "new@example.com",
            "user_metadata": {"first_name": "Jane"},
        },
        "email_data": {
            "email_action_type": action,
            "token": "123456",
            "token_hash": "hash-plain",
            "token_new": "",
            "token_hash_new": "",
            "redirect_to": "https://app.example.com/welcome?from=email",
            **email_data,
        },
    }


@patch("posthoganalytics.capture")
@patch("posthoganalytics.feature_enabled", return_value=True)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestSupabaseAuthEmails(APIBaseTest):
    def setUp(self):
        super().setUp()
        sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, sender.id)
        self.template = self._template("Supabase sign up")
        make_transactional(self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None)
        self.config = SupabaseAuthEmailConfig.objects.for_team(self.team.id).create(
            team=self.team,
            supabase_url="https://abcdefgh.supabase.co",
            hook_secret=HOOK_SECRET,
            templates={
                "signup": str(self.template.id),
                "email_change": str(self.template.id),
                "reauthentication": str(self.template.id),
                "email_changed_notification": str(self.template.id),
            },
        )
        self.hook_url = f"/webhooks/messaging/supabase/{self.team.id}/send-email"
        self.settings_url = f"/api/projects/{self.team.id}/messaging_supabase_auth_emails/settings/"
        self.starter_url = f"/api/projects/{self.team.id}/messaging_supabase_auth_emails/starter_templates/"

    def _template(self, name: str, *, sensitive: bool = True) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team=self.team,
            name=name,
            content={"email": {"subject": "Confirm", "html": "<a href='{{ variables.confirmation_url }}'>Go</a>"}},
            type="email",
            sensitive=sensitive,
        )

    def _post_hook(
        self,
        payload: dict[str, Any],
        *,
        key: bytes = SIGNING_KEY,
        webhook_id: str = "msg_1",
        signing_keys: list[bytes] | None = None,
    ):
        body = json.dumps(payload).encode()
        self.client.logout()
        return self.client.post(
            self.hook_url,
            data=body,
            content_type="application/json",
            headers=_signed_headers(body, key=key, webhook_id=webhook_id, signing_keys=signing_keys),
        )

    @parameterized.expand(
        [
            (
                "signup",
                _payload("signup"),
                [("current@example.com", "123456", "hash-plain")],
            ),
            (
                # Secure email change: Supabase swaps the hashes, so the current address gets the `_new` one.
                "secure_email_change",
                _payload("email_change", token_new="654321", token_hash_new="hash-new"),
                [("current@example.com", "123456", "hash-new"), ("new@example.com", "654321", "hash-plain")],
            ),
            (
                "email_change",
                _payload("email_change"),
                [("new@example.com", "123456", "hash-plain")],
            ),
            # Reauthentication has no verify link, only the code.
            ("reauthentication", _payload("reauthentication"), [("current@example.com", "123456", "hash-plain")]),
            # An unmapped notification is skipped rather than failing the user's request.
            ("unmapped_notification", _payload("password_changed_notification"), []),
            # The alert goes to the replaced address, so the owner hears about a takeover.
            (
                "email_changed_notification",
                _payload("email_changed_notification", user_email="new@example.com", old_email="current@example.com"),
                [("current@example.com", "123456", "hash-plain")],
            ),
            # A phone-only user adding an email has no current address.
            (
                "phone_only_email_change",
                _payload("email_change", user_email=""),
                [("new@example.com", "123456", "hash-plain")],
            ),
        ]
    )
    def test_sends_each_auth_email_through_its_template(self, mock_post, _flag, capture, _name, payload, expected):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})

        response = self._post_hook(payload)
        # Supabase retries with a new webhook id, so the sends must still share their idempotency keys.
        retry = self._post_hook(payload, webhook_id="msg_2")

        assert response.status_code == retry.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {}
        calls = [call.kwargs["json"] for call in mock_post.call_args_list]
        sent, resent = calls[: len(expected)], calls[len(expected) :]
        assert [(s["to"], s["variables"]["token"], s["variables"]["token_hash"]) for s in sent] == expected
        assert [s["idempotency_key"] for s in resent] == [s["idempotency_key"] for s in sent]
        # Supabase drops the hook after 5 seconds, so no send may wait longer than the shared budget.
        assert all(call.kwargs["timeout"] <= SEND_BUDGET_SECONDS for call in mock_post.call_args_list)
        action = payload["email_data"]["email_action_type"]
        for index, (send, (_to, _token, token_hash)) in enumerate(zip(sent, expected)):
            assert send["distinct_id"] == "8d0c0b6e-0000-4000-8000-000000000001"
            assert send["idempotency_key"] == f"supabase-{REQUEST_ID}-{index}"
            assert send["variables"]["confirmation_url"] == (
                ""
                if action == "reauthentication"
                else f"https://abcdefgh.supabase.co/auth/v1/verify?token={token_hash}&type={action}"
                "&redirect_to=https%3A%2F%2Fapp.example.com%2Fwelcome%3Ffrom%3Demail"
            )
            assert send["variables"]["user_metadata"] == {"first_name": "Jane"}
        # Only failures are tracked, so the event volume doesn't grow with the customer's traffic.
        assert not any(c.kwargs.get("event") == "supabase auth email hook" for c in capture.call_args_list)

    @parameterized.expand(
        [
            ("wrong_secret", "signup", {"key": b"x" * 32}, {}, None, 401, "other"),
            ("no_template_for_the_email", "signup", {}, {"templates": {}}, None, 400, "signup"),
            ("no_project_url", "signup", {}, {"supabase_url": ""}, None, 400, "signup"),
            # The payload names the email type, so an unknown one is reported as "other".
            ("unknown_email_type", "made_up_type", {}, {}, None, 400, "other"),
            ("over_quota", "signup", {}, {}, 429, 429, "signup"),
            ("pipeline_down", "signup", {}, {}, 500, 503, "signup"),
        ]
    )
    def test_answers_an_error_supabase_can_show_the_user(
        self,
        mock_post,
        _flag,
        capture,
        _name,
        action,
        sign_with,
        config_changes,
        cdp_status,
        expected_code,
        reported_action,
    ):
        for field, value in config_changes.items():
            setattr(self.config, field, value)
        self.config.save()
        if cdp_status:
            mock_post.return_value = MagicMock(
                status_code=cdp_status, json=lambda: {"error": "quota_limited"} if cdp_status == 429 else {}
            )

        response = self._post_hook(_payload(action), **sign_with)

        # Supabase only passes our message on when it comes with a 200. An unverified request still gets a 401.
        assert response.status_code == (401 if expected_code == 401 else 200)
        assert response.json()["error"]["http_code"] == expected_code
        assert response.json()["error"]["message"]
        assert mock_post.called == bool(cdp_status)
        hook_events = [
            c.kwargs["properties"]
            for c in capture.call_args_list
            if c.kwargs.get("event") == "supabase auth email hook"
        ]
        # An unverified request could come from anyone, so it records no usage for the team.
        assert [(e["status"], e["email_action_type"]) for e in hook_events] == (
            [] if expected_code == 401 else [(expected_code, reported_action)]
        )

    def test_settings_keep_the_secret_write_only_and_take_only_transactional_templates(
        self, _mock_post, _flag, _capture
    ):
        response = self.client.patch(
            self.settings_url, {"supabase_url": "https://abcdefgh.supabase.co/"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["supabase_url"] == "https://abcdefgh.supabase.co"
        assert response.json()["has_hook_secret"] is True
        assert "hook_secret" not in response.json()
        assert "email" not in {t["value"] for t in response.json()["email_types"]}
        assert response.json()["hook_url"].endswith(self.hook_url)

        not_transactional = self._template("Newsletter")
        not_sensitive = self._template("Plain reset", sensitive=False)
        make_transactional(self.team.id, not_sensitive.id, user_id=self.user.id, from_integration_id=None)
        for template in (not_transactional, not_sensitive):
            response = self.client.patch(
                self.settings_url, {"templates": {"recovery": str(template.id)}}, format="json"
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["attr"] == "templates"

        response = self.client.patch(self.settings_url, {"hook_secret": "whsec_short"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "hook_secret"

    def test_starter_templates_cover_the_core_auth_emails_once(self, _mock_post, _flag, _capture):
        response = self.client.post(self.starter_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        templates = response.json()["templates"]
        assert set(templates) == {
            "signup",
            "invite",
            "magiclink",
            "recovery",
            "email_change",
            "reauthentication",
            "email_changed_notification",
        }
        # Mapped types keep their template.
        assert templates["signup"] == str(self.template.id)
        created = MessageTemplate.objects.filter(team=self.team, name__startswith="Supabase: ")
        assert created.count() == 3
        assert all(t.sensitive and t.transactional_hog_flow_id for t in created)
        for template in created:
            design = template.content["email"]["design"]
            assert validate_design(design) == []
            # Native blocks, so each part opens on its own in the editor rather than as one raw HTML block.
            block_types = [c["type"] for c in design["body"]["rows"][0]["columns"][0]["contents"]]
            assert "html" not in block_types and "heading" in block_types

        again = self.client.post(self.starter_url)
        assert again.json()["templates"] == templates

    def test_mapping_a_template_needs_editor_access_to_its_workflow(self, _mock_post, _flag, _capture):
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        # Admins bypass object-level access, so the check needs a plain member.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        restricted = self._template("Supabase invite")
        # The creator of a workflow keeps access to it, so another user creates this one.
        make_transactional(self.team.id, restricted.id, user_id=None, from_integration_id=None)
        restricted.refresh_from_db()
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(restricted.transactional_hog_flow_id),
            access_level="none",
        )
        mapped = {**self.config.templates, "invite": str(restricted.id)}

        denied_mapping = self.client.patch(self.settings_url, {"templates": mapped}, format="json")
        self.config.templates = mapped
        self.config.save()
        # Once an admin maps it, a new secret would let the member sign hook calls that send it.
        denied_secret = self.client.patch(self.settings_url, {"hook_secret": HOOK_SECRET}, format="json")

        assert denied_mapping.status_code == status.HTTP_403_FORBIDDEN, denied_mapping.json()
        assert denied_secret.status_code == status.HTTP_403_FORBIDDEN, denied_secret.json()

    def test_hides_the_settings_but_keeps_sending_while_the_flag_is_off(self, mock_post, flag, _capture):
        flag.return_value = False
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})

        assert self.client.get(self.settings_url).status_code == status.HTTP_404_NOT_FOUND
        # A connected project's sign-ups must not break when the flag rolls back.
        assert self._post_hook(_payload("signup")).json() == {}
        assert mock_post.called

    def test_disconnect_clears_the_settings_so_the_hook_refuses_calls(self, mock_post, _flag, _capture):
        response = self.client.delete(self.settings_url)
        hook = self._post_hook(_payload("signup"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (response.json()["supabase_url"], response.json()["has_hook_secret"], response.json()["templates"]) == (
            "",
            False,
            {},
        )
        assert hook.status_code == status.HTTP_401_UNAUTHORIZED
        assert not mock_post.called

    def test_first_save_works_before_a_secret_is_stored(self, _mock_post, _flag, _capture):
        self.config.delete()

        starter = self.client.post(self.starter_url)
        saved = self.client.patch(self.settings_url, {"supabase_url": "https://abcdefgh.supabase.co"}, format="json")

        assert starter.status_code == status.HTTP_200_OK, starter.json()
        assert saved.status_code == status.HTTP_200_OK, saved.json()
        assert saved.json()["has_hook_secret"] is False

    @parameterized.expand([("deleted", {"deleted": True}), ("no_longer_sensitive", {"sensitive": False})])
    def test_a_mapped_template_that_cannot_send_fails_cleanly_and_gets_a_starter_replacement(
        self, mock_post, _flag, _capture, _name, change
    ):
        MessageTemplate.objects.filter(id=self.template.id).update(**change)

        response = self._post_hook(_payload("signup"))
        self.client.force_login(self.user)
        starter = self.client.post(self.starter_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["error"]["http_code"] == 400
        assert "template" not in response.json()["error"]["message"].lower()
        assert not mock_post.called
        assert starter.status_code == status.HTTP_200_OK, starter.json()
        assert starter.json()["templates"]["signup"] != str(self.template.id)

    # While a secret rotates, Supabase signs with each one, so the stored secret can sign either position.
    @parameterized.expand([("stored_secret_last", True), ("stored_secret_first", False)])
    def test_accepts_a_header_signed_with_an_old_and_a_new_secret(self, mock_post, _flag, _capture, _name, other_first):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "invocation-1"})
        other = b"o" * 32

        response = self._post_hook(
            _payload("signup"), signing_keys=[other, SIGNING_KEY] if other_first else [SIGNING_KEY, other]
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {}
        assert mock_post.called
