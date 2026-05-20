from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.legal_documents.backend.logic import pandadoc as pandadoc_client
from products.legal_documents.backend.models import LegalDocument
from products.legal_documents.backend.tasks.tasks import retry_send_pandadoc_envelope


class TestRetrySendPandaDocEnvelopeTask(APIBaseTest):
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

    def test_calls_send_when_envelope_still_awaiting_signature(self) -> None:
        with patch("products.legal_documents.backend.tasks.tasks.send_pandadoc_envelope_now") as send_mock:
            retry_send_pandadoc_envelope(str(self.document.id))
        send_mock.assert_called_once()
        sent_doc = send_mock.call_args.args[0]
        self.assertEqual(sent_doc.id, self.document.id)

    def test_skips_send_when_row_already_signed(self) -> None:
        self.document.status = LegalDocument.Status.SIGNED
        self.document.save(update_fields=["status"])
        with patch("products.legal_documents.backend.tasks.tasks.send_pandadoc_envelope_now") as send_mock:
            retry_send_pandadoc_envelope(str(self.document.id))
        send_mock.assert_not_called()

    def test_skips_when_row_has_no_pandadoc_envelope_id(self) -> None:
        self.document.pandadoc_document_id = ""
        self.document.save(update_fields=["pandadoc_document_id"])
        with patch("products.legal_documents.backend.tasks.tasks.send_pandadoc_envelope_now") as send_mock:
            retry_send_pandadoc_envelope(str(self.document.id))
        send_mock.assert_not_called()

    def test_raises_so_celery_autoretries_when_pandadoc_still_unreachable(self) -> None:
        # Celery's @shared_task autoretry_for=(PandaDocError,) re-enqueues the
        # task when this exception escapes. The retry cadence itself is owned
        # by the decorator — here we verify the exception isn't swallowed.
        with patch(
            "products.legal_documents.backend.tasks.tasks.send_pandadoc_envelope_now",
            side_effect=pandadoc_client.PandaDocError("still down"),
        ):
            with self.assertRaises(pandadoc_client.PandaDocError):
                retry_send_pandadoc_envelope(str(self.document.id))

    def test_missing_row_is_a_noop(self) -> None:
        with patch("products.legal_documents.backend.tasks.tasks.send_pandadoc_envelope_now") as send_mock:
            retry_send_pandadoc_envelope("00000000-0000-0000-0000-000000000000")
        send_mock.assert_not_called()
