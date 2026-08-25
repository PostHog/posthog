import hmac
import json
import hashlib
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership

from products.legal_documents.backend.facade import api as legal_api
from products.legal_documents.backend.models import LegalDocument

BAA_PAYLOAD = {
    "document_type": "BAA",
    "company_name": "Acme, Inc.",
    "company_address": "1 Analytics Way, SF CA",
    "representative_email": "ada@acme.example",
}

DPA_PAYLOAD = {
    "document_type": "DPA",
    "company_name": "Acme, Inc.",
    "company_address": "1 Analytics Way, SF CA",
    "representative_email": "ada@acme.example",
}


def _billing_with_addons(addon_types_subscribed: set[str]) -> dict[str, Any]:
    return {
        "products": [
            {
                "type": "platform_and_support",
                "addons": [{"type": addon_type, "subscribed": True} for addon_type in addon_types_subscribed]
                + [{"type": "unrelated", "subscribed": False}],
            }
        ]
    }


@override_settings(CLOUD_DEPLOYMENT="US")
class TestLegalDocumentAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/organizations/{self.organization.id}/legal_documents/"

    @parameterized.expand([("boost",), ("scale",), ("enterprise",)])
    @patch("products.legal_documents.backend.logic.BillingManager")
    def test_create_baa_with_qualifying_addon_succeeds(self, addon_type: str, mock_manager_cls) -> None:
        mock_manager_cls.return_value.get_billing.return_value = _billing_with_addons({addon_type})

        response = self.client.post(self.url, BAA_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        row = LegalDocument.objects.get(id=response.json()["id"])
        self.assertEqual(row.document_type, "BAA")
        self.assertEqual(row.organization_id, self.organization.id)
        self.assertEqual(row.created_by_id, self.user.id)

    @patch("products.legal_documents.backend.logic.BillingManager")
    def test_create_baa_without_qualifying_addon_is_forbidden(self, mock_manager_cls) -> None:
        mock_manager_cls.return_value.get_billing.return_value = _billing_with_addons(set())

        response = self.client.post(self.url, BAA_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Boost, Scale, or Enterprise", response.json()["detail"])
        self.assertFalse(LegalDocument.objects.exists())

    def test_create_dpa_succeeds(self) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

    def test_create_dpa_ignores_unknown_dpa_mode_field(self) -> None:
        # dpa_mode is a frontend-only preview toggle — extra keys are silently dropped.
        response = self.client.post(self.url, {**DPA_PAYLOAD, "dpa_mode": "fairytale"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_without_address_is_rejected(self) -> None:
        payload = {**DPA_PAYLOAD}
        payload.pop("company_address")
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company_address", response.json()["attr"])

    def test_create_msa_is_rejected_from_public_api(self) -> None:
        # MSAs only exist via Django admin upload — the public serializer's
        # ChoiceField does not list MSA, so a POST should 400 on document_type.
        payload = {**DPA_PAYLOAD, "document_type": "MSA"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("document_type", response.json()["attr"])
        self.assertFalse(LegalDocument.objects.exists())

    def test_list_is_scoped_to_current_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        LegalDocument.objects.create(
            organization=other_org,
            document_type="DPA",
            company_name="Other Co",
            company_address="Elsewhere",
            representative_email="bob@other.example",
        )
        self.client.post(self.url, DPA_PAYLOAD, format="json")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(len(ids), 1)

    def test_activity_log_row_is_written_on_create(self) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = ActivityLog.objects.filter(scope="LegalDocument", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None  # mypy
        self.assertEqual(str(log.organization_id), str(self.organization.id))
        assert log.detail is not None  # mypy
        self.assertEqual(log.detail["context"]["document_type"], "DPA")
        self.assertEqual(log.detail["context"]["company_name"], "Acme, Inc.")

    def test_anonymous_user_is_unauthorized(self) -> None:
        self.client.logout()
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_create_returns_default_status(self) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["status"], "submitted_for_signature")

    @patch("products.legal_documents.backend.logic.posthoganalytics.capture")
    def test_create_fires_submitted_analytics_event(self, mock_capture) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        row = LegalDocument.objects.get(id=response.json()["id"])

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["event"], "legal document submitted")
        props = kwargs["properties"]
        self.assertEqual(props["legal_document_id"], str(row.id))
        self.assertEqual(props["document_type"], "DPA")
        self.assertEqual(props["company_name"], "Acme, Inc.")
        # Old per-row webhook secret is no longer part of the event payload —
        # PandaDoc is now hit directly, so there's nothing to echo back.
        self.assertNotIn("legal_document_secret", props)

    @patch("products.legal_documents.backend.logic.posthoganalytics.capture")
    def test_create_baa_fires_submitted_event(self, mock_capture) -> None:
        with patch(
            "products.legal_documents.backend.logic.has_qualifying_baa_addon",
            return_value=True,
        ):
            response = self.client.post(self.url, BAA_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["event"], "legal document submitted")
        self.assertEqual(mock_capture.call_args.kwargs["properties"]["document_type"], "BAA")

    def test_regular_member_cannot_list(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_member_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(LegalDocument.objects.exists())

    def test_owner_can_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_only_one_dpa_per_organization(self) -> None:
        first = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already has a DPA", second.json()["detail"])
        self.assertEqual(LegalDocument.objects.filter(document_type="DPA").count(), 1)

    @patch("products.legal_documents.backend.logic.has_qualifying_baa_addon", return_value=True)
    def test_only_one_baa_per_organization(self, _mock_addon) -> None:
        first = self.client.post(self.url, BAA_PAYLOAD, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.url, BAA_PAYLOAD, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already has a BAA", second.json()["detail"])
        self.assertEqual(LegalDocument.objects.filter(document_type="BAA").count(), 1)

    @patch("products.legal_documents.backend.logic.has_qualifying_baa_addon", return_value=True)
    def test_baa_and_dpa_can_coexist_in_same_organization(self, _mock_addon) -> None:
        baa_response = self.client.post(self.url, BAA_PAYLOAD, format="json")
        dpa_response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(baa_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(dpa_response.status_code, status.HTTP_201_CREATED)

    def test_different_organizations_can_each_have_their_own_dpa(self) -> None:
        self.client.post(self.url, DPA_PAYLOAD, format="json")

        other_org = Organization.objects.create(name="Other Co")
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.ADMIN
        )
        other_url = f"/api/organizations/{other_org.id}/legal_documents/"
        response = self.client.post(other_url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_db_constraint_blocks_direct_model_duplicates(self) -> None:
        LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
        )
        with self.assertRaises(IntegrityError):
            LegalDocument.objects.create(
                organization=self.organization,
                document_type="DPA",
                company_name="Acme again",
                company_address="somewhere else",
                representative_email="ada@acme.example",
            )


@override_settings(CLOUD_DEPLOYMENT="US")
class TestLegalDocumentDownloadEndpoint(APIBaseTest):
    """
    The `GET .../download` proxy hands back a short-lived presigned URL to the
    signed PDF in object storage. The PDF itself lives at legal_documents/{id}.pdf.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
            signed_pdf_stored=True,
            pandadoc_document_id="doc_123",
            created_by=self.user,
        )
        self.url = f"/api/organizations/{self.organization.id}/legal_documents/{self.document.id}/download"

    def test_signed_document_returns_302_to_presigned_url(self) -> None:
        with patch(
            "products.legal_documents.backend.logic.object_storage.get_presigned_url",
            return_value="https://s3.example/signed-url?token=abc",
        ) as presign_mock:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "https://s3.example/signed-url?token=abc")
        presign_mock.assert_called_once()
        # Key should be under the legal_documents prefix.
        args, kwargs = presign_mock.call_args
        self.assertTrue(args[0].endswith(f"{self.document.id}.pdf"))

    def test_unsigned_document_returns_404(self) -> None:
        self.document.status = LegalDocument.Status.SUBMITTED_FOR_SIGNATURE
        self.document.save()
        with patch("products.legal_documents.backend.logic.object_storage.get_presigned_url") as presign_mock:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        presign_mock.assert_not_called()

    def test_signed_but_unarchived_document_returns_404(self) -> None:
        # The signature lands before the PDF archive job runs. Until the file is
        # stored, the download must 404 instead of redirecting to a missing S3 key.
        self.document.signed_pdf_stored = False
        self.document.save(update_fields=["signed_pdf_stored"])
        with patch("products.legal_documents.backend.logic.object_storage.get_presigned_url") as presign_mock:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        presign_mock.assert_not_called()

    def test_unknown_document_returns_404(self) -> None:
        bogus_url = (
            f"/api/organizations/{self.organization.id}/legal_documents/00000000-0000-0000-0000-000000000000/download"
        )
        response = self.client.get(bogus_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regular_member_cannot_download(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_organization_download_is_blocked(self) -> None:
        other_org = Organization.objects.create(name="Other Co")
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.ADMIN
        )
        # Same document id but accessed under the wrong org's path.
        url = f"/api/organizations/{other_org.id}/legal_documents/{self.document.id}/download"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_user_without_membership_can_download(self) -> None:
        # PostHog staff need to fetch signed PDFs from the Django admin without
        # joining the customer's org first. Drop the membership entirely and
        # flip is_staff — the request should still 302 to the presigned URL.
        self.organization_membership.delete()
        self.user.is_staff = True
        self.user.save()
        with patch(
            "products.legal_documents.backend.logic.object_storage.get_presigned_url",
            return_value="https://s3.example/signed-url?token=abc",
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)


@override_settings(CLOUD_DEPLOYMENT="US")
class TestLegalDocumentDeleteEndpoint(APIBaseTest):
    """
    Self-serve DELETE for an unsigned legal document. Voids the underlying
    PandaDoc envelope, removes the row, and frees the
    unique-per-org-per-type constraint so a fresh document can be generated
    (e.g., with a different signer). Signed documents stay admin-only.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            pandadoc_document_id="doc_123",
            created_by=self.user,
        )
        self.url = f"/api/organizations/{self.organization.id}/legal_documents/{self.document.id}/"

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_unsigned_document_deletes_and_voids_pandadoc(self, mock_pandadoc_cls) -> None:
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.content)
        self.assertFalse(LegalDocument.objects.filter(id=self.document.id).exists())
        mock_pandadoc_cls.return_value.void_document.assert_called_once_with(document_id="doc_123")

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_delete_frees_unique_constraint_so_new_dpa_can_be_created(self, _mock_pandadoc_cls) -> None:
        # The whole point of the feature: after deleting an unsigned DPA, a
        # second POST with a corrected signer should succeed.
        list_url = f"/api/organizations/{self.organization.id}/legal_documents/"
        blocked = self.client.post(list_url, DPA_PAYLOAD, format="json")
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

        deleted = self.client.delete(self.url)
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT, deleted.content)

        replacement = self.client.post(
            list_url,
            {**DPA_PAYLOAD, "representative_email": "joakim@hubexo.example"},
            format="json",
        )
        self.assertEqual(replacement.status_code, status.HTTP_201_CREATED, replacement.content)
        new_row = LegalDocument.objects.get(id=replacement.json()["id"])
        self.assertEqual(new_row.representative_email, "joakim@hubexo.example")

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_signed_document_cannot_be_deleted_via_api(self, mock_pandadoc_cls) -> None:
        # The facade re-reads the row under select_for_update inside the
        # delete transaction, so a webhook that flips status to signed
        # between request start and lock acquisition lands here too — the
        # gate is enforced on the locked row, not on a stale read.
        self.document.status = LegalDocument.Status.SIGNED
        self.document.save()

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertTrue(LegalDocument.objects.filter(id=self.document.id).exists())
        mock_pandadoc_cls.return_value.void_document.assert_not_called()

    @parameterized.expand(
        [
            ("unknown_uuid", "00000000-0000-0000-0000-000000000000"),
            ("invalid_uuid", "not-a-uuid"),
        ]
    )
    def test_nonexistent_or_invalid_pk_returns_404(self, _name: str, pk: str) -> None:
        url = f"/api/organizations/{self.organization.id}/legal_documents/{pk}/"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_cross_organization_delete_is_blocked(self, mock_pandadoc_cls) -> None:
        # Same document id, accessed from another org the user happens to
        # also admin. The lookup is org-scoped so the row should look 404 from
        # that path — and the actual row stays put.
        other_org = Organization.objects.create(name="Other Co")
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.ADMIN
        )
        url = f"/api/organizations/{other_org.id}/legal_documents/{self.document.id}/"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(LegalDocument.objects.filter(id=self.document.id).exists())
        mock_pandadoc_cls.return_value.void_document.assert_not_called()

    def test_regular_member_cannot_delete(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(LegalDocument.objects.filter(id=self.document.id).exists())

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_pandadoc_void_failure_returns_503_and_keeps_row(self, mock_pandadoc_cls) -> None:
        # Self-serve delete runs PandaDoc void in strict mode: if void fails,
        # the facade's transaction rolls back and the row stays. The
        # alternative (deleting the row anyway) would mean telling the user
        # the envelope was cancelled when it wasn't, leaving the original
        # signer with a still-completable document.
        from products.legal_documents.backend.logic import pandadoc as pandadoc_module

        mock_pandadoc_cls.return_value.void_document.side_effect = pandadoc_module.PandaDocError("boom")

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "legal_document_void_failed")
        self.assertTrue(LegalDocument.objects.filter(id=self.document.id).exists())

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    def test_activity_log_row_is_written_on_delete(self, _mock_pandadoc_cls) -> None:
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = ActivityLog.objects.filter(scope="LegalDocument", activity="deleted").first()
        self.assertIsNotNone(log, "expected a deleted-activity log entry from ModelActivityMixin")
        assert log is not None  # mypy
        self.assertEqual(str(log.organization_id), str(self.organization.id))

    def test_anonymous_user_cannot_delete(self) -> None:
        self.client.logout()
        response = self.client.delete(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertTrue(LegalDocument.objects.filter(id=self.document.id).exists())


@override_settings(CLOUD_DEPLOYMENT="US")
class TestLegalDocumentPandaDocWebhook(APIBaseTest):
    SECRET = "pandadoc-test-secret"
    BAA_TEMPLATE_ID = "tpl_baa"
    DPA_TEMPLATE_ID = "tpl_dpa"

    def setUp(self) -> None:
        super().setUp()
        self.document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            pandadoc_document_id="doc_123",
            created_by=self.user,
        )
        self.url = "/api/legal_documents/pandadoc"
        self.client.logout()

    def _completed_payload(self, pandadoc_document_id: str = "doc_123", template_id: str | None = None) -> list[dict]:
        # PandaDoc's `document.completed` webhook doesn't carry a signed-PDF
        # URL — we pull the PDF ourselves via the public API. The fixture
        # mirrors the real shape (no download_link, no public_url).
        return [
            {
                "event": "document_state_changed",
                "data": {
                    "id": pandadoc_document_id,
                    "status": "document.completed",
                    "template": {"id": template_id or self.DPA_TEMPLATE_ID},
                },
            }
        ]

    def _draft_payload(self, pandadoc_document_id: str = "doc_123", template_id: str | None = None) -> list[dict]:
        return [
            {
                "event": "document_state_changed",
                "data": {
                    "id": pandadoc_document_id,
                    "status": "document.draft",
                    "template": {"id": template_id or self.DPA_TEMPLATE_ID},
                },
            }
        ]

    def _post_raw(self, body: bytes, signature: str):
        # DRF's test client types `data` as str even though it accepts bytes at
        # runtime; decode so mypy doesn't complain while the wire payload stays
        # the exact bytes we signed (UTF-8 round-trips cleanly).
        return self.client.generic(
            "POST",
            self.url,
            data=body.decode("utf-8", errors="surrogateescape"),
            content_type="application/json",
            HTTP_X_PANDADOC_SIGNATURE=signature,
        )

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def _override(self):
        return self.settings(
            PANDADOC_WEBHOOK_SECRET=self.SECRET,
            PANDADOC_BAA_TEMPLATE_ID=self.BAA_TEMPLATE_ID,
            PANDADOC_DPA_TEMPLATE_ID=self.DPA_TEMPLATE_ID,
        )

    def test_valid_signature_flips_status_and_archives_pdf_in_background(self) -> None:
        # The signature is recorded synchronously; the PDF archive runs from the
        # scheduled background task (fired here via captureOnCommitCallbacks).
        fake_stream = object()

        @contextmanager
        def fake_stream_cm(*, document_id):  # noqa: ARG001
            yield fake_stream

        body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=fake_stream_cm,
            ) as stream_mock,
            patch("products.legal_documents.backend.logic.object_storage.write_stream") as write_mock,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        self.assertTrue(self.document.signed_pdf_stored)
        stream_mock.assert_called_once_with(document_id="doc_123")
        write_mock.assert_called_once()
        args, kwargs = write_mock.call_args
        # Positional args: (key, fileobj); content-type rides in extras.
        self.assertTrue(args[0].endswith(f"{self.document.id}.pdf"))
        self.assertIs(args[1], fake_stream)
        self.assertEqual(kwargs["extras"], {"ContentType": "application/pdf"})

    def test_archive_failure_leaves_row_signed_but_unarchived(self) -> None:
        # The whole point of the decoupling: a PDF download failure no longer
        # blocks the signature. The row is signed and the webhook returns 200;
        # only signed_pdf_stored stays False for the reconciliation sweep to fix.
        from products.legal_documents.backend.logic import pandadoc as pandadoc_module

        body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=pandadoc_module.PandaDocError("network boom"),
            ) as stream_mock,
            patch("products.legal_documents.backend.logic.object_storage.write_stream") as write_mock,
        ):
            # Celery runs eagerly in tests, and autoretry_for re-raises as Retry once
            # every attempt is exhausted, the same pattern as the task's real retry behavior.
            with self.assertRaises(Retry), self.captureOnCommitCallbacks(execute=True):
                response = self._post_raw(body, self._sign(body))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stream_mock.assert_called_once_with(document_id="doc_123")
        write_mock.assert_not_called()
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        self.assertFalse(self.document.signed_pdf_stored)

    def test_invalid_signature_returns_404(self) -> None:
        body = json.dumps(self._completed_payload()).encode("utf-8")
        with self._override():
            response = self._post_raw(body, "not-the-right-signature")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    def test_unknown_document_id_returns_204(self) -> None:
        # Sibling cloud instance scenario: signature is valid but the document
        # belongs to a different instance. 2xx so PandaDoc doesn't retry.
        body = json.dumps(self._completed_payload(pandadoc_document_id="unknown")).encode("utf-8")
        with self._override():
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_uninteresting_state_event_is_noop(self) -> None:
        # document.sent / document.viewed / etc. — we only act on draft + completed.
        payload = self._completed_payload()
        payload[0]["data"]["status"] = "document.sent"
        body = json.dumps(payload).encode("utf-8")
        with self._override():
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    def test_draft_event_dispatches_send(self) -> None:
        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document") as send_mock,
        ):
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["document_id"], "doc_123")

    def test_draft_event_swallows_pandadoc_send_failure(self) -> None:
        from products.legal_documents.backend.logic import pandadoc as pandadoc_client

        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document",
                side_effect=pandadoc_client.PandaDocError("boom"),
            ),
        ):
            response = self._post_raw(body, self._sign(body))
        # Endpoint still 2xx — we don't want PandaDoc to retry.
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_draft_event_for_already_signed_document_is_a_noop(self) -> None:
        self.document.status = "signed"
        self.document.save()

        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document") as send_mock,
        ):
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send_mock.assert_not_called()

    def test_template_mismatch_does_not_flip_row(self) -> None:
        # Completed event with BAA template id for what's actually a DPA row in the DB
        # — reject so a misconfigured template can never mark the wrong document.
        body = json.dumps(self._completed_payload(template_id=self.BAA_TEMPLATE_ID)).encode("utf-8")
        with self._override():
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    def test_invalid_json_returns_400(self) -> None:
        body = b"not-valid-json{"
        with self._override():
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_replayed_completed_event_skips_side_effects(self) -> None:
        @contextmanager
        def fake_stream_cm(*, document_id):  # noqa: ARG001
            yield object()

        # First delivery: stream + flip to signed.
        body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=fake_stream_cm,
            ),
            patch("products.legal_documents.backend.logic.object_storage.write_stream"),
        ):
            first = self._post_raw(body, self._sign(body))
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")

        # Replay: must not re-stream the PDF, re-upload, or re-fire analytics.
        # PandaDoc retries / cross-instance fan-out both land here.
        replay_body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document"
            ) as stream_spy,
            patch("products.legal_documents.backend.logic.object_storage.write_stream") as write_spy,
            patch("products.legal_documents.backend.logic.fire_legal_document_signed_event") as event_spy,
        ):
            response = self._post_raw(replay_body, self._sign(replay_body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stream_spy.assert_not_called()
        write_spy.assert_not_called()
        event_spy.assert_not_called()

    def _swap_to_baa_document(self) -> None:
        """The default fixture is a DPA. For BAA-side-effect tests, retarget it."""
        self.document.document_type = "BAA"
        self.document.save(update_fields=["document_type"])

    @contextmanager
    def _fake_pdf_pipeline(self):
        @contextmanager
        def fake_stream_cm(*, document_id):  # noqa: ARG001
            yield object()

        with (
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=fake_stream_cm,
            ),
            patch("products.legal_documents.backend.logic.object_storage.write_stream"),
        ):
            yield

    # Both flags send customer data to a third party the BAA does not cover: one to the LLM
    # subprocessors, one to the replay ML training mirror. Signing a BAA has to clear both.
    AI_OPT_OUT_FLAGS = [("is_ai_data_processing_approved",), ("is_ai_training_opted_in",)]

    @parameterized.expand(AI_OPT_OUT_FLAGS)
    def test_signed_baa_opts_organization_out(self, flag: str) -> None:
        self._swap_to_baa_document()
        # Both default to True now — explicitly set so this isn't accidentally testing the default.
        setattr(self.organization, flag, True)
        self.organization.save(update_fields=[flag])

        body = json.dumps(self._completed_payload(template_id=self.BAA_TEMPLATE_ID)).encode("utf-8")
        with self._override(), self._fake_pdf_pipeline():
            response = self._post_raw(body, self._sign(body))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertFalse(getattr(self.organization, flag))

    @parameterized.expand(AI_OPT_OUT_FLAGS)
    def test_signed_dpa_leaves_ai_flags_alone(self, flag: str) -> None:
        # Default fixture is a DPA, so don't swap.
        setattr(self.organization, flag, True)
        self.organization.save(update_fields=[flag])

        body = json.dumps(self._completed_payload()).encode("utf-8")
        with self._override(), self._fake_pdf_pipeline():
            response = self._post_raw(body, self._sign(body))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertTrue(getattr(self.organization, flag))

    def test_signed_baa_emails_org_owners(self) -> None:
        self._swap_to_baa_document()
        # Promote the test user to OWNER so the email path has a recipient.
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.OWNER
        membership.save(update_fields=["level"])

        body = json.dumps(self._completed_payload(template_id=self.BAA_TEMPLATE_ID)).encode("utf-8")
        with (
            self._override(),
            self._fake_pdf_pipeline(),
            patch("products.legal_documents.backend.logic.is_email_available", return_value=True),
            patch("products.legal_documents.backend.logic.EmailMessage") as email_cls,
        ):
            response = self._post_raw(body, self._sign(body))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        email_cls.assert_called_once()
        kwargs = email_cls.call_args.kwargs
        self.assertEqual(kwargs["template_name"], "baa_signed_ai_disabled")
        self.assertTrue(kwargs["use_http"])
        self.assertEqual(kwargs["template_context"]["organization_name"], self.organization.name)
        self.assertIn("organization-ai-consent", kwargs["template_context"]["ai_settings_url"])
        instance = email_cls.return_value
        instance.add_user_recipient.assert_called_once_with(self.user)
        instance.send.assert_called_once_with(send_async=True)

    def test_signed_baa_skips_email_when_no_owner(self) -> None:
        self._swap_to_baa_document()
        # Default APIBaseTest membership is MEMBER, not OWNER — so no recipients.

        body = json.dumps(self._completed_payload(template_id=self.BAA_TEMPLATE_ID)).encode("utf-8")
        with (
            self._override(),
            self._fake_pdf_pipeline(),
            patch("products.legal_documents.backend.logic.is_email_available", return_value=True),
            patch("products.legal_documents.backend.logic.EmailMessage") as email_cls,
        ):
            response = self._post_raw(body, self._sign(body))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        email_cls.assert_not_called()
        self.organization.refresh_from_db()
        # Opt-out still happens even when there are no owners to notify.
        self.assertFalse(self.organization.is_ai_data_processing_approved)


@override_settings(CLOUD_DEPLOYMENT="US")
class TestLegalDocumentReconciliation(APIBaseTest):
    """
    The reconciliation sweep and the background archive task — the safety net
    that recovers signatures whose completion webhook was dropped, throttled, or
    204'd, and re-archives signed rows whose PDF never landed.
    """

    def setUp(self) -> None:
        super().setUp()
        self.document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            pandadoc_document_id="doc_123",
            created_by=self.user,
        )

    @contextmanager
    def _fake_pdf_pipeline(self):
        @contextmanager
        def fake_stream_cm(*, document_id):  # noqa: ARG001
            yield object()

        with (
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=fake_stream_cm,
            ),
            patch("products.legal_documents.backend.logic.object_storage.write_stream"),
        ):
            yield

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_marks_completed_pending_document_signed(self, status_mock) -> None:
        status_mock.return_value = "document.completed"
        with self._fake_pdf_pipeline(), self.captureOnCommitCallbacks(execute=True):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 1)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        self.assertTrue(self.document.signed_pdf_stored)

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_captures_the_signed_event_through_a_scoped_client(self, status_mock) -> None:
        # The sweep runs in a Celery worker, where the global analytics client's
        # background flush may never run before the process exits. Losing the signed
        # event here would leave a working sweep indistinguishable from a broken one,
        # since that event is what the outage was detected on.
        status_mock.return_value = "document.completed"
        with (
            patch("products.legal_documents.backend.facade.api.ph_scoped_capture") as scoped_mock,
            patch("products.legal_documents.backend.logic.posthoganalytics.capture") as global_mock,
        ):
            capture = scoped_mock.return_value.__enter__.return_value
            with self._fake_pdf_pipeline(), self.captureOnCommitCallbacks(execute=True):
                legal_api.reconcile_pending_signatures()

        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["event"], "legal document signed")
        global_mock.assert_not_called()

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_skips_documents_older_than_lookback_window(self, status_mock) -> None:
        # Abandoned envelopes must not be polled forever, or the sweep re-asks PandaDoc
        # about them every 15 minutes. 30 days is deliberately inside the window this
        # started with, so widening it back would fail here rather than pass quietly.
        status_mock.return_value = "document.completed"
        LegalDocument.objects.filter(id=self.document.id).update(created_at=timezone.now() - timedelta(days=30))

        result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 0)
        status_mock.assert_not_called()
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_leaves_still_pending_document_alone(self, status_mock) -> None:
        status_mock.return_value = "document.sent"
        result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 0)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_continues_past_a_row_that_raises(self, status_mock) -> None:
        # Each org can only hold one DPA (unique constraint), so the extra pending
        # rows live in separate orgs. list_pending_signature_documents orders
        # oldest-first, so pin created_at explicitly to make the middle row deterministic.
        middle_org = Organization.objects.create(name="Middle Co")
        last_org = Organization.objects.create(name="Last Co")
        middle = LegalDocument.objects.create(
            organization=middle_org,
            document_type="DPA",
            company_name="Middle Co",
            company_address="Elsewhere",
            representative_email="middle@other.example",
            pandadoc_document_id="doc_middle",
            created_by=self.user,
        )
        last = LegalDocument.objects.create(
            organization=last_org,
            document_type="DPA",
            company_name="Last Co",
            company_address="Elsewhere",
            representative_email="last@other.example",
            pandadoc_document_id="doc_last",
            created_by=self.user,
        )
        now = timezone.now()
        LegalDocument.objects.filter(id=self.document.id).update(created_at=now - timedelta(minutes=2))
        LegalDocument.objects.filter(id=middle.id).update(created_at=now - timedelta(minutes=1))
        LegalDocument.objects.filter(id=last.id).update(created_at=now)

        def status_side_effect(*, document_id):
            if document_id == "doc_middle":
                raise RuntimeError("unexpected PandaDoc client bug")
            return "document.completed"

        status_mock.side_effect = status_side_effect

        with self._fake_pdf_pipeline(), self.captureOnCommitCallbacks(execute=True):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 2)
        self.assertEqual(result.errors, 1)
        self.document.refresh_from_db()
        middle.refresh_from_db()
        last.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        self.assertEqual(middle.status, "submitted_for_signature")
        self.assertEqual(last.status, "signed")

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_schedules_archive_once_for_newly_signed_row(self, status_mock) -> None:
        status_mock.return_value = "document.completed"
        with (
            patch(
                "products.legal_documents.backend.tasks.tasks.archive_signed_legal_document_pdf.apply_async"
            ) as enqueue_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 1)
        self.assertEqual(result.archives_requeued, 0)
        enqueue_mock.assert_called_once_with(args=[str(self.document.id)], countdown=0)

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status")
    def test_reconcile_staggers_archives_one_per_second(self, status_mock) -> None:
        # PandaDoc caps downloads per account, shared with live signings, so a backlog
        # drain has to spread out rather than enqueue every archive at once.
        for i in (1, 2):
            org = self.create_organization_with_features([])
            LegalDocument.objects.create(
                organization=org,
                document_type="DPA",
                company_name=f"Later Co {i}",
                company_address="2 Analytics Way",
                representative_email=f"later{i}@other.example",
                pandadoc_document_id=f"doc_later_{i}",
                created_by=self.user,
            )
        status_mock.return_value = "document.completed"

        with (
            patch(
                "products.legal_documents.backend.tasks.tasks.archive_signed_legal_document_pdf.apply_async"
            ) as enqueue_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 3)
        countdowns = [call.kwargs["countdown"] for call in enqueue_mock.call_args_list]
        self.assertEqual(countdowns, [0, 1, 2])

    def test_reconcile_skips_side_effects_for_concurrently_signed_row(self) -> None:
        # A webhook can sign the row between the reconcile loop reading its queryset
        # snapshot and processing it. BAA side effects include emailing org owners,
        # so re-running them here would send a second email for a signature the
        # webhook already handled.
        self.document.document_type = "BAA"
        self.document.save(update_fields=["document_type"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        def status_side_effect(*, document_id):  # noqa: ARG001
            LegalDocument.objects.filter(id=self.document.id).update(status=LegalDocument.Status.SIGNED)
            return "document.completed"

        with patch(
            "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status",
            side_effect=status_side_effect,
        ):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 0)
        self.assertEqual(result.errors, 0)
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.is_ai_data_processing_approved)

    def test_reconcile_leaves_pending_document_alone_when_pandadoc_unreachable(self) -> None:
        from products.legal_documents.backend.logic import pandadoc as pandadoc_module

        with patch(
            "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.get_document_status",
            side_effect=pandadoc_module.PandaDocError("network boom"),
        ):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.newly_signed, 0)
        self.assertEqual(result.errors, 0)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

    def test_reconcile_requeues_archive_for_signed_row_missing_pdf(self) -> None:
        self.document.status = LegalDocument.Status.SIGNED
        self.document.save(update_fields=["status"])

        with self._fake_pdf_pipeline(), self.captureOnCommitCallbacks(execute=True):
            result = legal_api.reconcile_pending_signatures()

        self.assertEqual(result.archives_requeued, 1)
        self.document.refresh_from_db()
        self.assertTrue(self.document.signed_pdf_stored)

    def test_archive_is_noop_when_already_stored(self) -> None:
        self.document.status = LegalDocument.Status.SIGNED
        self.document.signed_pdf_stored = True
        self.document.save(update_fields=["status", "signed_pdf_stored"])

        with patch(
            "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document"
        ) as stream_mock:
            legal_api.archive_signed_pdf(self.document.id)
        stream_mock.assert_not_called()

    def test_archive_failure_raises_for_task_retry(self) -> None:
        from products.legal_documents.backend.logic import pandadoc as pandadoc_module

        self.document.status = LegalDocument.Status.SIGNED
        self.document.save(update_fields=["status"])

        with patch(
            "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
            side_effect=pandadoc_module.PandaDocError("boom"),
        ):
            with self.assertRaises(legal_api.LegalDocumentPdfArchiveFailed):
                legal_api.archive_signed_pdf(self.document.id)
        self.document.refresh_from_db()
        self.assertFalse(self.document.signed_pdf_stored)


@override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
class TestLegalDocumentsSelfHostedGate(APIBaseTest):
    """
    Self-hosted instances must never hit the PandaDoc integration. The API
    should 404 regardless of auth, and the PandaDoc webhook should 404 even
    with a valid signature.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_list_404s_on_self_hosted(self) -> None:
        response = self.client.get(f"/api/organizations/{self.organization.id}/legal_documents/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_404s_on_self_hosted(self) -> None:
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/legal_documents/", DPA_PAYLOAD, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(LegalDocument.objects.exists())

    def test_delete_404s_on_self_hosted(self) -> None:
        # Rows shouldn't exist on self-hosted but we still want the gate to
        # respond 404 regardless of what's in the DB — never reach PandaDoc.
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
        )
        response = self.client.delete(f"/api/organizations/{self.organization.id}/legal_documents/{document.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(LegalDocument.objects.filter(id=document.id).exists())

    def test_pandadoc_webhook_404s_on_self_hosted_even_with_valid_signature(self) -> None:
        self.client.logout()
        secret = "any-secret"
        body = b'{"event": "document_state_changed"}'
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        with self.settings(PANDADOC_WEBHOOK_SECRET=secret):
            response = self.client.generic(
                "POST",
                "/api/legal_documents/pandadoc",
                data=body.decode("utf-8"),
                content_type="application/json",
                HTTP_X_PANDADOC_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
