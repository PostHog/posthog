import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.scoping import team_scope

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.presentation.views.transactional_code_emails import CodeEmailUpdateSerializer
from products.workflows.backend.facade.models import HogFlow
from products.workflows.backend.facade.transactional_emails import create_code_email_workflow
from products.workflows.backend.facade.writes import destroy_workflow


@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalCodeEmails(APIBaseTest):
    def _code_email(self, key: str, team_id: int | None = None) -> TransactionalEmailKey:
        team_id = team_id or self.team.id
        hog_flow_id = create_code_email_workflow(team_id=team_id, key=key)
        return TransactionalEmailKey.objects.for_team(team_id, canonical=True).create(
            team_id=team_id, key=key, hog_flow_id=hog_flow_id
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/transactional_code_emails/{suffix}"

    def _limit_to_members_with_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def test_lists_the_projects_code_emails_with_their_labels(self, _post, _flag):
        reset = self._code_email("password-reset")
        self._code_email("order-shipped")
        self._code_email("other-team-email", team_id=self.create_team_with_organization(self.organization).id)
        self.client.patch(
            self._url(f"{reset.id}/"),
            {
                "description": "Sent when someone asks to reset their password",
                "tags": ["auth"],
                "source_url": "https://github.com/acme/web/blob/main/src/emails/password-reset.tsx",
            },
            format="json",
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        rows = {row["key"]: row for row in response.json()}
        assert set(rows) == {"password-reset", "order-shipped"}
        assert rows["password-reset"] | {"created_at": None} == {
            "id": str(reset.id),
            "key": "password-reset",
            "hog_flow_id": str(reset.hog_flow_id),
            "description": "Sent when someone asks to reset their password",
            "tags": ["auth"],
            "source_url": "https://github.com/acme/web/blob/main/src/emails/password-reset.tsx",
            "sensitive": True,
            "created_at": None,
            "user_access_level": "editor",
        }
        assert rows["order-shipped"]["description"] == ""
        assert rows["order-shipped"]["tags"] == []
        assert rows["order-shipped"]["source_url"] is None

    @parameterized.expand(["workflow_deleted", "template_took_the_key"])
    def test_hides_a_key_that_no_longer_sends_as_code(self, _post, _flag, reason):
        gone = self._code_email("welcome")
        if reason == "workflow_deleted":
            destroy_workflow(team_id=self.team.id, hog_flow_id=gone.hog_flow_id)
        else:
            MessageTemplate.objects.create(team=self.team, name="Welcome", key="welcome")
        kept = self._code_email("receipt")

        assert [row["key"] for row in self.client.get(self._url()).json()] == ["receipt"]
        assert self.client.get(self._url(f"{gone.id}/")).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url(f"{kept.id}/")).json()["key"] == "receipt"

    def test_another_projects_code_email_is_not_found(self, _post, _flag):
        other = self._code_email("invoice-paid", team_id=self.create_team_with_organization(self.organization).id)

        assert self.client.get(self._url(f"{other.id}/")).status_code == status.HTTP_404_NOT_FOUND
        patched = self.client.patch(self._url(f"{other.id}/"), {"description": "Mine now"}, format="json")
        assert patched.status_code == status.HTTP_404_NOT_FOUND

    def _sending_config(self, email: TransactionalEmailKey) -> dict:
        with team_scope(self.team.id):
            flow = HogFlow.objects.filter(team_id=self.team.id, id=email.hog_flow_id).get()
            revisions = flow.revisions.count()
        return {
            "version": flow.version,
            "revisions": revisions,
            "actions": flow.actions,
            "edges": flow.edges,
            "trigger": flow.trigger,
            "draft": flow.draft,
        }

    def test_update_changes_only_the_fields_sent(self, _post, _flag):
        email = self._code_email("magic-link")
        sending_config = self._sending_config(email)
        self.client.patch(
            self._url(f"{email.id}/"),
            {"description": "Sign-in link", "tags": ["auth", "login"], "source_url": "https://example.com/a.py"},
            format="json",
        )

        response = self.client.patch(self._url(f"{email.id}/"), {"tags": ["auth"], "source_url": ""}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert {k: response.json()[k] for k in ("description", "tags", "source_url")} == {
            "description": "Sign-in link",
            "tags": ["auth"],
            "source_url": None,
        }
        assert self.client.get(self._url(f"{email.id}/")).json()["tags"] == ["auth"]
        assert self._sending_config(email) == sending_config

    @parameterized.expand(
        [
            ("description", {"description": "Sign-in link"}),
            ("tags", {"tags": ["auth"]}),
        ]
    )
    def test_a_workflow_save_based_on_older_labels_is_rejected(self, _post, _flag, _name, labels):
        with time_machine.travel("2026-06-15T12:00:00Z", tick=False):
            email = self._code_email("magic-link")
            loaded = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{email.hog_flow_id}").json()
        with time_machine.travel("2026-06-15T12:05:00Z", tick=False):
            assert self.client.patch(self._url(f"{email.id}/"), labels, format="json").status_code == 200

            stale = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{email.hog_flow_id}",
                {"description": "Older copy", "tags": ["older"], "base_updated_at": loaded["updated_at"]},
                format="json",
            )

        assert stale.status_code == status.HTTP_409_CONFLICT, stale.json()
        stored = self.client.get(self._url(f"{email.id}/")).json()
        assert {key: stored[key] for key in labels} == labels

    def test_rejects_a_source_url_that_is_not_a_web_link(self, _post, _flag):
        email = self._code_email("export-ready")

        response = self.client.patch(self._url(f"{email.id}/"), {"source_url": "javascript:alert(1)"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "source_url"

    def test_follows_the_readers_access_to_each_email_workflow(self, _post, _flag):
        hidden = self._code_email("payroll")
        read_only = self._code_email("receipt")
        self._limit_to_members_with_access()
        for email, level in ((hidden, "none"), (read_only, "viewer")):
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                resource_id=str(email.hog_flow_id),
                access_level=level,
                organization_member_id=self.organization_membership.id,
            )

        assert [(row["key"], row["user_access_level"]) for row in self.client.get(self._url()).json()] == [
            ("receipt", "viewer")
        ]
        assert self.client.get(self._url(f"{hidden.id}/")).status_code == status.HTTP_404_NOT_FOUND
        patched = self.client.patch(self._url(f"{read_only.id}/"), {"description": "Edited"}, format="json")
        assert patched.status_code == status.HTTP_403_FORBIDDEN

    def test_is_not_found_without_the_transactional_email_flags(self, _post, flag):
        flag.return_value = False

        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND


class TestCodeEmailUpdateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("ftp://example.com/emails/receipt.py", False),
            ("javascript:alert(1)", False),
            ("src/emails/receipt.py", False),
            ("https://example.com/" + "a" * 2048, False),
            ("https://github.com/acme/web/blob/main/src/emails/receipt.tsx", True),
            ("http://git.example.com/acme/billing/emails/receipt.py", True),
        ]
    )
    def test_source_url_must_be_a_web_link(self, source_url: str, valid: bool) -> None:
        assert CodeEmailUpdateSerializer(data={"source_url": source_url}, partial=True).is_valid() is valid

    def test_an_empty_source_url_unlinks_the_file(self) -> None:
        serializer = CodeEmailUpdateSerializer(data={"source_url": ""}, partial=True)

        assert serializer.is_valid()
        assert serializer.validated_data["source_url"] is None
