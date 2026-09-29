import hmac
import json
import time
import base64
import hashlib
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.user import User

from products.growth.backend.account_audits import COOLDOWN, AccountAuditService
from products.growth.backend.models import AccountAuditAdmission, AccountAuditCredential


@override_settings(GROWTH_ENRICHMENT_INTERNAL_TEAM_ID=2)
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
        if isinstance(payload, dict):
            payload = {"reason": "testing", **payload}
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
                "products.growth.backend.account_audits.resolve_audit_actor_for_team", return_value=self.user.id
            ) as actor,
            patch("products.growth.backend.account_audits.get_skill_prompt", return_value=MagicMock()) as skill,
            patch("products.growth.backend.account_audits.create_audit_task", return_value=uuid4()) as dispatch,
        ):
            yield actor, skill, dispatch

    @parameterized.expand([("US", 2, True), ("EU", 1, False)])
    def test_accepts_a_signed_delivery_and_reuses_the_same_run(
        self, region: str, growth_team_id: int, explicit_team: bool
    ) -> None:
        payload: dict[str, object] = {"organization_id": str(self.organization.id)}
        if explicit_team:
            payload["team_id"] = self.team.id
        with (
            self.settings(CLOUD_DEPLOYMENT=region, GROWTH_ENRICHMENT_INTERNAL_TEAM_ID=growth_team_id),
            self._request_patches() as (_, skill, dispatch),
        ):
            first = self._post(payload)
            other_team = Team.objects.create(organization=self.organization, name="Recently active project")
            FileSystemViewLog.objects.create(team=other_team, user=self.user, type="dashboard", ref="1")
            second = self._post(payload)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        admission = AccountAuditAdmission.objects.unscoped().get(credential=self.credential)
        self.assertEqual(first.json(), {"task_run_id": str(admission.task_run_id), "team_id": self.team.id})
        self.assertEqual(second.json(), {"task_run_id": str(admission.task_run_id), "team_id": self.team.id})
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(dispatch.call_args.kwargs["team_id"], self.team.id)
        skill.assert_called_once_with(team_id=growth_team_id, skill_name="onboarding-account-audit")

    @parameterized.expand([(False, False, False), (False, False, True), (True, False, True), (False, True, True)])
    def test_defaults_to_the_oldest_eligible_root_project_on_tied_activity(
        self, is_demo: bool, pending_deletion: bool, has_views: bool
    ) -> None:
        self.team.is_demo = is_demo
        self.team.save(update_fields=["is_demo"])
        self.team.project.is_pending_deletion = pending_deletion
        self.team.project.save(update_fields=["is_pending_deletion"])
        next_team = Team.objects.create(organization=self.organization, name="Renamed project")
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        if has_views:
            for team in (self.team, next_team, child):
                FileSystemViewLog.objects.create(team=team, user=self.user, type="dashboard", ref="1")
            other_user = User.objects.create(email="other-viewer@example.com")
            FileSystemViewLog.objects.create(team=child, user=other_user, type="dashboard", ref="1")
        expected_id = next_team.id if is_demo or pending_deletion else self.team.id
        with self._request_patches() as (actor, _, dispatch):
            response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["team_id"], expected_id)
        actor.assert_called_once_with(expected_id)
        self.assertEqual(dispatch.call_args.kwargs["team_id"], expected_id)

    @parameterized.expand([(29, False), (30, False), (31, False), (29, True)])
    @time_machine.travel("2026-01-01T00:00:00Z", tick=False)
    def test_selects_distinct_recent_viewers_unless_a_team_is_explicit(
        self, days_ago: int, explicit_team: bool
    ) -> None:
        self.team.project.created_at = timezone.now() - timedelta(days=90)
        self.team.project.save(update_fields=["created_at"])
        active_team = Team.objects.create(organization=self.organization, name="Active project")
        other_user = User.objects.create(email="other-viewer@example.com")
        for ref in ("1", "2", "3"):
            FileSystemViewLog.objects.create(team=self.team, user=self.user, type="dashboard", ref=ref)
        for user in (self.user, other_user):
            FileSystemViewLog.objects.create(
                team=active_team,
                user=user,
                type="dashboard",
                ref="1",
                viewed_at=timezone.now() - timedelta(days=days_ago),
            )
        payload: dict[str, object] = {"organization_id": str(self.organization.id)}
        if explicit_team:
            payload["team_id"] = self.team.id
        expected_id = self.team.id if explicit_team or days_ago > 30 else active_team.id
        with self._request_patches() as (_, _, dispatch):
            response = self._post(payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["team_id"], expected_id)
        self.assertEqual(dispatch.call_args.kwargs["team_id"], expected_id)

    def test_rejects_an_organization_without_an_eligible_default_project(self) -> None:
        self.team.is_demo = True
        self.team.save(update_fields=["is_demo"])
        with self._request_patches() as (_, _, dispatch):
            response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 400)
        dispatch.assert_not_called()

    def test_persists_reason_and_uses_the_selected_skill(self) -> None:
        explicit_team = Team.objects.create(organization=self.organization, name="Explicit project")
        payload = {
            "organization_id": str(self.organization.id),
            "team_id": explicit_team.id,
            "reason": "activation-review",
            "skill_name": "activation-audit",
        }
        with self._request_patches() as (_, skill, dispatch):
            response = self._post(payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["team_id"], explicit_team.id)
        skill.assert_called_once_with(team_id=2, skill_name="activation-audit")
        self.assertEqual(dispatch.call_args.kwargs["skill"], skill.return_value)
        admission = AccountAuditAdmission.objects.unscoped().get(credential=self.credential)
        self.assertEqual(admission.reason, "activation-review")
        self.assertEqual(admission.skill_name, "activation-audit")

    def test_failed_run_creation_rolls_back_and_allows_retry(self) -> None:
        payload = {"organization_id": str(self.organization.id)}
        queued = MagicMock()

        def fail_creation(**kwargs: object) -> SimpleNamespace:
            transaction.on_commit(queued)
            return SimpleNamespace(latest_run=None)

        with (
            self._request_patches() as (_, skill, create),
            patch(
                "products.growth.backend.audit_execution.tasks_facade.create_and_run_task", side_effect=fail_creation
            ) as native_create,
            patch("products.notebooks.backend.facade.api.capture_notebook_created") as notebook_capture,
        ):
            from products.growth.backend.audit_execution import create_audit_task
            from products.notebooks.backend.facade.api import get_notebook

            skill.return_value = SimpleNamespace(body="Audit this project.", version=1)
            create.side_effect = create_audit_task
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self._post(payload).status_code, 503)
            self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())
            notebook_id = native_create.call_args.kwargs["extra_run_state"]["audit_notebook_short_id"]
            self.assertIsNone(get_notebook(self.team.id, notebook_id))
            queued.assert_not_called()
            notebook_capture.assert_not_called()
            native_create.side_effect = None
            native_create.return_value = SimpleNamespace(latest_run=SimpleNamespace(id=uuid4()))
            self.assertEqual(self._post(payload).status_code, 202)
            self.assertEqual(AccountAuditAdmission.objects.unscoped().count(), 1)

    def test_rejects_invalid_missing_and_stale_signatures(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        cases = [
            ("invalid", "not-base64", None),
            ("stale", None, str(int(time.time()) - 301)),
        ]
        with self._request_patches():
            for name, signature, timestamp in cases:
                with self.subTest(name=name):
                    self.assertEqual(self._post(payload, signature=signature, timestamp=timestamp).status_code, 401)
            response = self.client.post(
                self.url,
                data=json.dumps(payload).encode(),
                content_type="application/json",
                HTTP_X_POSTHOG_AUDIT_KEY=str(self.credential.public_key_id),
                HTTP_WEBHOOK_ID="delivery-missing-signature",
                HTTP_WEBHOOK_TIMESTAMP=str(int(time.time())),
            )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_a_signature_for_a_different_raw_body(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches():
            response = self._post(payload, signing_body=b'{"organization_id":"different","team_id":1}')

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_malformed_and_extra_payloads(self) -> None:
        payloads = [
            b"{",
            json.dumps({"organization_id": str(self.organization.id)}).encode(),
            json.dumps({"organization_id": str(self.organization.id), "team_id": self.team.id, "extra": True}).encode(),
        ]
        for field, invalid in [
            ("reason", ""),
            ("reason", "   "),
            ("reason", None),
            ("reason", 1),
            ("reason", "x" * 501),
            ("skill_name", ""),
            ("skill_name", None),
            ("skill_name", 1),
            ("skill_name", "x" * 65),
            ("team_id", None),
            ("team_id", True),
            ("team_id", "1"),
            ("team_id", 0),
        ]:
            payloads.append(
                json.dumps({"organization_id": str(self.organization.id), "reason": "testing", field: invalid}).encode()
            )
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

        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_without_ai_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, dispatch):
            response = self._post(payload)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(dispatch.called)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_when_the_audit_skill_is_unavailable_without_admitting(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (_, skill, dispatch):
            skill.return_value = None
            response = self._post(payload)

        self.assertEqual(response.status_code, 400)
        skill.assert_called_once_with(team_id=2, skill_name="onboarding-account-audit")
        self.assertFalse(dispatch.called)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_a_team_from_another_organization(self) -> None:
        other_org = Organization.objects.create(name="Other organization", is_ai_data_processing_approved=True)
        Team.objects.create(organization=other_org, name="Other team")
        payload = {"organization_id": str(other_org.id), "team_id": self.team.id}
        with self._request_patches() as (_, _, dispatch):
            response = self._post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(dispatch.called)

    def test_rejects_when_no_team_actor_is_available(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches() as (actor, _, dispatch):
            actor.return_value = None
            response = self._post(payload)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(dispatch.called)

    @parameterized.expand([("team_id",), ("reason",), ("skill_name",)])
    def test_rejects_a_repeated_delivery_with_changed_parameters(self, field: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        changed_payload = {**payload, field: other_team.id if field == "team_id" else "another-audit"}
        with self._request_patches() as (_, _, dispatch):
            self.assertEqual(self._post(payload).status_code, 202)
            response = self._post(changed_payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "This delivery ID has another audit request.")
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(AccountAuditAdmission.objects.unscoped().count(), 1)

    @time_machine.travel("2026-01-01T00:00:00Z", tick=False)
    def test_accepts_a_new_delivery_at_the_cooldown_boundary(self) -> None:
        AccountAuditAdmission.objects.unscoped().create(
            credential=self.credential,
            task_run_id=uuid4(),
            webhook_id="earlier-delivery",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )
        AccountAuditAdmission.objects.unscoped().filter(webhook_id="earlier-delivery").update(
            created_at=timezone.now() - COOLDOWN
        )
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self._request_patches():
            response = self._post(payload, webhook_id="new-delivery")

        self.assertEqual(response.status_code, 202)

    def test_admission_enforces_one_row_per_credential_delivery(self) -> None:
        AccountAuditAdmission.objects.unscoped().create(
            credential=self.credential,
            task_run_id=uuid4(),
            webhook_id="delivery-1",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountAuditAdmission.objects.unscoped().create(
                    credential=self.credential,
                    task_run_id=uuid4(),
                    webhook_id="delivery-1",
                    organization_id=self.organization.id,
                    team_id=self.team.id,
                )

    @parameterized.expand(
        [("revoked",), ("owner_inactive",), ("owner_not_staff",), ("unknown_key",), ("wrong_secret",)]
    )
    def test_rejects_an_ineligible_destination_credential(self, condition: str) -> None:
        if condition == "revoked":
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(is_active=False)
        elif condition == "owner_inactive":
            User.objects.filter(pk=self.user.pk).update(is_active=False)
        elif condition == "owner_not_staff":
            User.objects.filter(pk=self.user.pk).update(is_staff=False)
        elif condition == "unknown_key":
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(public_key_id=uuid4())
        else:
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(
                signing_secret=f"whsec_{base64.b64encode(b'b' * 32).decode()}"
            )
        with self._request_patches() as (_, _, dispatch):
            response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 401)
        dispatch.assert_not_called()
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_preserves_historic_admissions_when_an_owner_or_credential_is_deleted(self) -> None:
        owner = User.objects.create_user(email="audit-owner@example.com", password=None, first_name="Audit")
        credential = AccountAuditCredential.objects.create(owner=owner, signing_secret=self.secret)
        admission = AccountAuditAdmission.objects.unscoped().create(
            credential=credential,
            task_run_id=uuid4(),
            webhook_id="delivery-1",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )

        owner.delete()
        credential.refresh_from_db()
        self.assertIsNone(credential.owner)
        self.assertFalse(AccountAuditService._credential_is_eligible(credential))
        with self.assertRaises(ProtectedError):
            credential.delete()
        self.assertTrue(AccountAuditAdmission.objects.unscoped().filter(pk=admission.pk).exists())
