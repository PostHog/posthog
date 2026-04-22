from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import IntegrityError

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership

from products.legal_documents.backend.models import LegalDocument

BAA_PAYLOAD = {
    "document_type": "BAA",
    "company_name": "Acme, Inc.",
    "representative_name": "Ada Lovelace",
    "representative_title": "CEO",
    "representative_email": "ada@acme.example",
}

DPA_PAYLOAD = {
    "document_type": "DPA",
    "company_name": "Acme, Inc.",
    "company_address": "1 Analytics Way, SF CA",
    "representative_name": "Ada Lovelace",
    "representative_title": "CEO",
    "representative_email": "ada@acme.example",
    "dpa_mode": "pretty",
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
        self.assertEqual(row.dpa_mode, "")
        self.assertEqual(row.company_address, "")

    @patch("products.legal_documents.backend.logic.BillingManager")
    def test_create_baa_without_qualifying_addon_is_forbidden(self, mock_manager_cls) -> None:
        mock_manager_cls.return_value.get_billing.return_value = _billing_with_addons(set())

        response = self.client.post(self.url, BAA_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Boost, Scale, or Enterprise", response.json()["detail"])
        self.assertFalse(LegalDocument.objects.exists())

    def test_create_dpa_with_pretty_mode_succeeds(self) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        row = LegalDocument.objects.get(id=response.json()["id"])
        self.assertEqual(row.dpa_mode, "pretty")

    def test_create_dpa_with_lawyer_mode_succeeds(self) -> None:
        response = self.client.post(self.url, {**DPA_PAYLOAD, "dpa_mode": "lawyer"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand([("fairytale",), ("tswift",)])
    def test_create_dpa_with_preview_only_mode_is_rejected(self, dpa_mode: str) -> None:
        response = self.client.post(self.url, {**DPA_PAYLOAD, "dpa_mode": dpa_mode}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("preview-only", response.json()["detail"])

    def test_create_dpa_without_mode_is_rejected(self) -> None:
        payload = {**DPA_PAYLOAD}
        payload.pop("dpa_mode")
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_dpa_without_address_is_rejected(self) -> None:
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
            representative_name="Bob",
            representative_title="CTO",
            representative_email="bob@other.example",
            dpa_mode="lawyer",
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

    def test_create_returns_default_status_and_no_secret(self) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["status"], "submitted_for_signature")
        self.assertEqual(body["signed_document_url"], "")
        # Secret is generated server-side and MUST never reach the UI.
        self.assertNotIn("webhook_secret", body)
        # But the row itself has one so the webhook can verify it.
        row = LegalDocument.objects.get(id=body["id"])
        self.assertTrue(row.webhook_secret)
        self.assertGreaterEqual(len(row.webhook_secret), 32)

    @patch("products.legal_documents.backend.logic.posthoganalytics.capture")
    def test_create_fires_zapier_event_with_secret(self, mock_capture) -> None:
        response = self.client.post(self.url, DPA_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        row = LegalDocument.objects.get(id=response.json()["id"])

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["event"], "clicked Request DPA")
        props = kwargs["properties"]
        self.assertEqual(props["legal_document_id"], str(row.id))
        self.assertEqual(props["legal_document_secret"], row.webhook_secret)
        self.assertEqual(props["companyName"], "Acme, Inc.")

    @patch("products.legal_documents.backend.logic.posthoganalytics.capture")
    def test_create_baa_fires_submitted_baa_event(self, mock_capture) -> None:
        with patch(
            "products.legal_documents.backend.logic.has_qualifying_baa_addon",
            return_value=True,
        ):
            response = self.client.post(self.url, BAA_PAYLOAD, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["event"], "submitted BAA")

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
            representative_name="Ada",
            representative_title="CEO",
            representative_email="ada@acme.example",
            dpa_mode="pretty",
        )
        with self.assertRaises(IntegrityError):
            LegalDocument.objects.create(
                organization=self.organization,
                document_type="DPA",
                company_name="Acme again",
                company_address="somewhere else",
                representative_name="Ada",
                representative_title="CEO",
                representative_email="ada@acme.example",
                dpa_mode="lawyer",
            )


class TestLegalDocumentSignedWebhook(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_name="Ada Lovelace",
            representative_title="CEO",
            representative_email="ada@acme.example",
            dpa_mode="pretty",
            created_by=self.user,
        )
        self.url = "/api/legal_documents/signed"
        self.client.logout()  # webhook is public; no session cookie

    def _post(self, **overrides: Any):
        payload: dict[str, Any] = {
            "secret": self.document.webhook_secret,
            "signed_document_url": "https://app.pandadoc.com/s/signed.pdf",
        }
        payload.update(overrides)
        return self.client.post(self.url, payload, format="json")

    def test_valid_secret_flips_status_and_stores_url(self) -> None:
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "signed")
        self.assertEqual(self.document.signed_document_url, "https://app.pandadoc.com/s/signed.pdf")

    def test_wrong_secret_returns_404_and_leaves_document_unchanged(self) -> None:
        response = self._post(secret="nope")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "submitted_for_signature")
        self.assertEqual(self.document.signed_document_url, "")

    def test_unknown_secret_returns_404(self) -> None:
        response = self.client.post(
            self.url,
            {"secret": "whatever", "signed_document_url": "https://app.pandadoc.com/s/x.pdf"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_signed_url_returns_400(self) -> None:
        response = self.client.post(self.url, {"secret": self.document.webhook_secret}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_absolute_signed_url_returns_400(self) -> None:
        response = self._post(signed_document_url="ftp://bad")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
