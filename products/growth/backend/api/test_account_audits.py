import hmac
import json
import time
import base64
import hashlib
from contextlib import contextmanager
from io import StringIO
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.models.user import User

from products.growth.backend.api.account_audits import COOLDOWN, AccountAuditStartViewSet
from products.growth.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.workflows.backend.models import HogFlow


class TestAccountAuditStartAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.secret = f"whsec_{base64.b64encode(b'a' * 32).decode()}"
        self.credential = AccountAuditCredential.objects.create(
            owner=self.user,
            workflow_id=uuid4(),
            signing_secret=self.secret,
        )
        self.url = "/api/growth_account_audits/start/"

    def _post(
        self,
        payload: object,
        *,
        webhook_id: str = "delivery-1",
        timestamp: str | None = None,
        signature: str | None = None,
        signing_body: bytes | None = None,
    ):
        raw_body = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = timestamp if timestamp is not None else str(int(time.time()))
        signed_body = signing_body if signing_body is not None else raw_body
        signature = (
            signature
            or base64.b64encode(
                hmac.new(
                    b"a" * 32,
                    webhook_id.encode() + b"." + timestamp.encode() + b"." + signed_body,
                    hashlib.sha256,
                ).digest()
            ).decode()
        )
        return self.client.post(
            self.url,
            data=raw_body,
            content_type="application/json",
            HTTP_X_POSTHOG_AUDIT_KEY=str(self.credential.public_key_id),
            HTTP_WEBHOOK_ID=webhook_id,
            HTTP_WEBHOOK_TIMESTAMP=timestamp,
            HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
        )

    @contextmanager
    def _request_patches(self):
        with (
            patch(
                "products.growth.backend.api.account_audits.AccountAuditStartViewSet._credential_is_eligible",
                return_value=True,
            ) as eligible,
            patch(
                "products.growth.backend.api.account_audits.resolve_audit_actor_for_team", return_value=self.user.id
            ) as actor,
            patch("products.growth.backend.api.account_audits.get_skill_prompt", return_value=MagicMock()) as skill,
            patch("products.growth.backend.api.account_audits.async_to_sync", return_value=MagicMock()) as dispatch,
        ):
            yield eligible, actor, skill, dispatch

    def test_accepts_a_signed_delivery_and_retries_the_same_workflow(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, _, dispatch):
            first = self._post(payload)
            second = self._post(payload)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        admission = AccountAuditAdmission.objects.get(credential=self.credential)
        self.assertEqual(first.json(), {"workflow_id": str(admission.workflow_id)})
        self.assertEqual(second.json(), {"workflow_id": str(admission.workflow_id)})
        self.assertEqual(dispatch.return_value.call_count, 2)
        self.assertEqual(dispatch.return_value.call_args.kwargs["workflow_id"], str(admission.workflow_id))

    def test_accepts_a_duplicate_retry_when_temporal_already_started_the_workflow(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}

        def already_started(**kwargs):
            raise WorkflowAlreadyStartedError(kwargs["workflow_id"], "growth-account-audit")

        with self._request_patches() as (_, _, _, dispatch):
            dispatch.return_value.side_effect = already_started
            response = self._post(payload)

        self.assertEqual(response.status_code, 202)
        admission = AccountAuditAdmission.objects.get(credential=self.credential)
        self.assertEqual(response.json(), {"workflow_id": str(admission.workflow_id)})

    def test_rejects_a_temporal_conflict_for_another_workflow(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, _, dispatch):
            dispatch.return_value.side_effect = WorkflowAlreadyStartedError("another-workflow", "growth-account-audit")
            response = self._post(payload)

        self.assertEqual(response.status_code, 503)
        self.assertTrue(AccountAuditAdmission.objects.filter(credential=self.credential).exists())

    def test_rejects_invalid_missing_and_stale_signatures(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        cases = [
            ("invalid", {"signature": "v1,not-base64"}),
            ("stale", {"timestamp": str(int(time.time()) - 301)}),
        ]
        with self._request_patches():
            for name, options in cases:
                with self.subTest(name=name):
                    self.assertEqual(self._post(payload, **options).status_code, 401)
            response = self.client.post(
                self.url,
                data=json.dumps(payload).encode(),
                content_type="application/json",
                HTTP_X_POSTHOG_AUDIT_KEY=str(self.credential.public_key_id),
                HTTP_WEBHOOK_ID="delivery-missing-signature",
                HTTP_WEBHOOK_TIMESTAMP=str(int(time.time())),
            )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.exists())

    def test_rejects_a_signature_for_a_different_raw_body(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches():
            response = self._post(payload, signing_body=b'{"organization_id":"different","team_id":1}')

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.exists())

    def test_rejects_malformed_and_extra_payloads(self) -> None:
        payloads = [
            b"{",
            json.dumps({"organization_id": str(self.organization.id)}).encode(),
            json.dumps({"organization_id": str(self.organization.id), "team_id": self.team.id, "extra": True}).encode(),
        ]
        with self._request_patches():
            for index, raw_body in enumerate(payloads):
                timestamp = str(int(time.time()))
                signature = base64.b64encode(
                    hmac.new(
                        b"a" * 32,
                        f"delivery-{index}.{timestamp}.".encode() + raw_body,
                        hashlib.sha256,
                    ).digest()
                ).decode()
                with self.subTest(index=index):
                    response = self.client.post(
                        self.url,
                        data=raw_body,
                        content_type="application/json",
                        HTTP_X_POSTHOG_AUDIT_KEY=str(self.credential.public_key_id),
                        HTTP_WEBHOOK_ID=f"delivery-{index}",
                        HTTP_WEBHOOK_TIMESTAMP=timestamp,
                        HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
                    )
                    self.assertEqual(response.status_code, 400)

        self.assertFalse(AccountAuditAdmission.objects.exists())

    def test_rejects_without_ai_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, _, dispatch):
            response = self._post(payload)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(dispatch.return_value.called)
        self.assertFalse(AccountAuditAdmission.objects.exists())

    def test_rejects_when_the_audit_skill_is_unavailable_without_admitting(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, skill, dispatch):
            skill.return_value = None
            response = self._post(payload)

        self.assertEqual(response.status_code, 503)
        skill.assert_called_once_with(team_id=2, skill_name="onboarding-account-audit")
        self.assertFalse(dispatch.return_value.called)
        self.assertFalse(AccountAuditAdmission.objects.exists())

    def test_rejects_a_team_from_another_organization(self) -> None:
        payload = {"organization_id": str(uuid4()), "team_id": self.team.id}
        with self._request_patches() as (_, _, _, dispatch):
            response = self._post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(dispatch.return_value.called)

    def test_rejects_when_no_team_actor_is_available(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, actor, _, dispatch):
            actor.return_value = None
            response = self._post(payload)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(dispatch.return_value.called)

    def test_rejects_a_repeated_delivery_with_a_changed_target(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        changed_payload = {"organization_id": str(self.organization.id), "team_id": other_team.id}
        with self._request_patches() as (_, _, _, dispatch):
            self.assertEqual(self._post(payload).status_code, 202)
            response = self._post(changed_payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Wait seven days before starting another account audit.")
        self.assertIn("next_available_at", response.json())
        self.assertEqual(dispatch.return_value.call_count, 1)
        self.assertEqual(AccountAuditAdmission.objects.count(), 1)

    @time_machine.travel("2026-01-01T00:00:00Z", tick=False)
    def test_accepts_a_new_delivery_at_the_cooldown_boundary(self) -> None:
        AccountAuditAdmission.objects.create(
            credential=self.credential,
            webhook_id="earlier-delivery",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )
        AccountAuditAdmission.objects.filter(webhook_id="earlier-delivery").update(created_at=timezone.now() - COOLDOWN)
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches():
            response = self._post(payload, webhook_id="new-delivery")

        self.assertEqual(response.status_code, 202)

    def test_admission_enforces_one_row_per_credential_delivery(self) -> None:
        AccountAuditAdmission.objects.create(
            credential=self.credential,
            webhook_id="delivery-1",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountAuditAdmission.objects.create(
                    credential=self.credential,
                    webhook_id="delivery-1",
                    organization_id=self.organization.id,
                    team_id=self.team.id,
                )

    def _source_team(self) -> Team:
        source_team, _ = Team.objects.get_or_create(
            id=2,
            defaults={"organization": self.organization, "project": self.team.project, "name": "source"},
        )
        return source_team

    def test_credential_requires_an_active_staff_owner_and_matching_source_workflow(self) -> None:
        source_team = self._source_team()
        flow = HogFlow.objects.create(team=source_team, created_by=self.user, name="audit", status="active")
        self.credential.workflow_id = flow.id
        self.credential.save(update_fields=["workflow_id"])
        credential = AccountAuditCredential.objects.select_related("owner").get(pk=self.credential.pk)

        self.assertTrue(AccountAuditStartViewSet._credential_is_eligible(credential))
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        credential.refresh_from_db()
        self.assertFalse(AccountAuditStartViewSet._credential_is_eligible(credential))
        self.user.is_staff = True
        self.user.is_active = False
        self.user.save(update_fields=["is_staff", "is_active"])
        credential.refresh_from_db()
        self.assertFalse(AccountAuditStartViewSet._credential_is_eligible(credential))
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        flow.team = self.team
        flow.save(update_fields=["team"])
        credential.refresh_from_db()
        self.assertFalse(AccountAuditStartViewSet._credential_is_eligible(credential))

    def test_preserves_historic_admissions_when_an_owner_or_credential_is_deleted(self) -> None:
        owner = User.objects.create_user(email="audit-owner@example.com", password=None, first_name="Audit")
        credential = AccountAuditCredential.objects.create(owner=owner, workflow_id=uuid4(), signing_secret=self.secret)
        admission = AccountAuditAdmission.objects.create(
            credential=credential,
            webhook_id="delivery-1",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )

        owner.delete()
        credential.refresh_from_db()
        self.assertIsNone(credential.owner)
        self.assertFalse(AccountAuditStartViewSet._credential_is_eligible(credential))
        with self.assertRaises(ProtectedError):
            credential.delete()
        self.assertTrue(AccountAuditAdmission.objects.filter(pk=admission.pk).exists())


class TestProvisionAccountAuditCredential(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.source_team, _ = Team.objects.get_or_create(
            id=2,
            defaults={"organization": self.organization, "project": self.team.project, "name": "source"},
        )
        self.flow = HogFlow.objects.create(team=self.source_team, created_by=self.user, name="audit", status="active")

    def _command(self, *, rotate_key_id: UUID) -> None:
        call_command(
            "provision_account_audit_credential",
            "--owner-id",
            str(self.user.id),
            "--workflow-id",
            str(self.flow.id),
            "--rotate-key-id",
            str(rotate_key_id),
            stdout=StringIO(),
        )

    def test_rejects_rotating_a_credential_owned_by_another_user(self) -> None:
        other_user = User.objects.create_user(email="other-owner@example.com", password=None, first_name="Other")
        credential = AccountAuditCredential.objects.create(
            owner=other_user,
            workflow_id=self.flow.id,
            signing_secret="whsec_" + base64.b64encode(b"b" * 32).decode(),
        )

        with self.assertRaises(CommandError):
            self._command(rotate_key_id=credential.public_key_id)

        credential.refresh_from_db()
        self.assertTrue(credential.is_active)

    def test_rejects_rotating_a_credential_for_another_workflow(self) -> None:
        other_flow = HogFlow.objects.create(team=self.source_team, created_by=self.user, name="other", status="active")
        credential = AccountAuditCredential.objects.create(
            owner=self.user,
            workflow_id=other_flow.id,
            signing_secret="whsec_" + base64.b64encode(b"b" * 32).decode(),
        )

        with self.assertRaises(CommandError):
            self._command(rotate_key_id=credential.public_key_id)

        credential.refresh_from_db()
        self.assertTrue(credential.is_active)
