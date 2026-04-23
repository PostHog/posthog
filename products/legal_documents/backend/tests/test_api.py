import hmac
import json
import hashlib
from contextlib import contextmanager
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import IntegrityError
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership

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

    def test_valid_signature_streams_pdf_to_object_storage_and_flips_status(self) -> None:
        # The streaming handle is opaque to the webhook layer; we just need to
        # confirm it's threaded from PandaDoc into object storage.
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
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        stream_mock.assert_called_once_with(document_id="doc_123")
        write_mock.assert_called_once()
        args, kwargs = write_mock.call_args
        # Positional args: (key, fileobj); content-type rides in extras.
        self.assertTrue(args[0].endswith(f"{self.document.id}.pdf"))
        self.assertIs(args[1], fake_stream)
        self.assertEqual(kwargs["extras"], {"ContentType": "application/pdf"})

    def test_download_failure_returns_503_and_leaves_row_unsigned(self) -> None:
        from products.legal_documents.backend.logic import pandadoc as pandadoc_module

        body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document",
                side_effect=pandadoc_module.PandaDocError("network boom"),
            ),
            patch("products.legal_documents.backend.logic.object_storage.write_stream") as write_mock,
        ):
            response = self._post_raw(body, self._sign(body))

        # 503 surfaces so PandaDoc retries the delivery.
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        write_mock.assert_not_called()
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")

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

    def test_draft_event_dispatches_send_and_fires_slack(self) -> None:
        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document") as send_mock,
            patch("products.legal_documents.backend.logic.notify_slack_on_submit") as slack_mock,
        ):
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["document_id"], "doc_123")
        slack_mock.assert_called_once()

    def test_draft_event_skips_slack_if_pandadoc_send_fails(self) -> None:
        from products.legal_documents.backend.logic import pandadoc as pandadoc_client

        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document",
                side_effect=pandadoc_client.PandaDocError("boom"),
            ),
            patch("products.legal_documents.backend.logic.notify_slack_on_submit") as slack_mock,
        ):
            response = self._post_raw(body, self._sign(body))
        # Endpoint still 2xx (we don't want PandaDoc to retry) but Slack is skipped.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slack_mock.assert_not_called()

    def test_draft_event_for_already_signed_document_is_a_noop(self) -> None:
        self.document.status = "signed"
        self.document.save()

        body = json.dumps(self._draft_payload()).encode("utf-8")
        with (
            self._override(),
            patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.send_document") as send_mock,
            patch("products.legal_documents.backend.logic.notify_slack_on_submit") as slack_mock,
        ):
            response = self._post_raw(body, self._sign(body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send_mock.assert_not_called()
        slack_mock.assert_not_called()

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

        # Replay: must not re-stream the PDF, re-upload, or re-fire Slack /
        # analytics. PandaDoc retries / cross-instance fan-out both land here.
        replay_body = json.dumps(self._completed_payload()).encode("utf-8")
        with (
            self._override(),
            patch(
                "products.legal_documents.backend.logic.pandadoc_client.PandaDocClient.stream_document"
            ) as stream_spy,
            patch("products.legal_documents.backend.logic.object_storage.write_stream") as write_spy,
            patch("products.legal_documents.backend.logic.notify_slack_on_signed") as slack_spy,
            patch("products.legal_documents.backend.logic.fire_legal_document_signed_event") as event_spy,
        ):
            response = self._post_raw(replay_body, self._sign(replay_body))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stream_spy.assert_not_called()
        write_spy.assert_not_called()
        slack_spy.assert_not_called()
        event_spy.assert_not_called()


@override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
class TestLegalDocumentsSelfHostedGate(APIBaseTest):
    """
    Self-hosted instances must never hit the PandaDoc / Slack integrations. The
    API should 404 regardless of auth, and the PandaDoc webhook should 404 even
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
