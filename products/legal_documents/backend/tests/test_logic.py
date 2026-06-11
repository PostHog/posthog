from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from products.legal_documents.backend.logic import (
    delete_document,
    pandadoc as pandadoc_module,
)
from products.legal_documents.backend.models import LegalDocument


class TestDeleteDocument(APIBaseTest):
    def _document(self, **overrides: Any) -> LegalDocument:
        defaults: dict[str, Any] = {
            "organization": self.organization,
            "document_type": "DPA",
            "company_name": "Acme, Inc.",
            "company_address": "1 Analytics Way",
            "representative_email": "ada@acme.example",
            "pandadoc_document_id": "doc_123",
        }
        defaults.update(overrides)
        return LegalDocument.objects.create(**defaults)

    # --- Signed (admin path) ---

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_signed_document_skips_pandadoc_and_deletes_s3_pdf(self, mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # PandaDoc envelopes for signed documents are already complete; calling
        # void on them returns 423 and is pure Sentry noise.
        document = self._document(status=LegalDocument.Status.SIGNED)
        document_id = document.id

        delete_document(document)

        mock_pandadoc_cls.assert_not_called()
        mock_storage.delete.assert_called_once()
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    # --- Unsigned (both paths) ---

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_unsigned_document_voids_pandadoc_and_skips_s3(self, mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # Unsigned rows never have a PDF in object storage — only PandaDoc
        # webhook completion writes one — so the S3 round-trip is skipped.
        document = self._document()
        document_id = document.id

        delete_document(document)

        mock_pandadoc_cls.return_value.void_document.assert_called_once_with(document_id="doc_123")
        mock_storage.delete.assert_not_called()
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_pandadoc_failure_in_admin_mode_is_swallowed(self, _mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # Admin (default `strict_pandadoc=False`) path: PandaDoc unreachable or
        # locked envelope shouldn't block staff from removing a row. Stale
        # envelope on PandaDoc is preferable to staff being unable to delete.
        mock_pandadoc_cls.return_value.void_document.side_effect = pandadoc_module.PandaDocError("boom")
        document = self._document()
        document_id = document.id

        delete_document(document)

        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_strict_pandadoc_raises_and_does_not_delete_row(self, _mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # Self-serve path (`strict_pandadoc=True`): a PandaDoc failure must
        # bubble up so the surrounding facade transaction rolls back. The row
        # stays; the API surfaces 503 and the user can retry.
        mock_pandadoc_cls.return_value.void_document.side_effect = pandadoc_module.PandaDocError("boom")
        document = self._document()
        document_id = document.id

        with self.assertRaises(pandadoc_module.PandaDocError):
            delete_document(document, strict_pandadoc=True)

        self.assertTrue(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_s3_failure_in_signed_path_is_swallowed(self, mock_storage: Any, _mock_pandadoc_cls: Any) -> None:
        # S3 only runs for signed rows. If it fails, the row still goes —
        # a stale PDF orphan in S3 is preferable to an undeletable row.
        mock_storage.delete.side_effect = RuntimeError("s3 down")
        document = self._document(status=LegalDocument.Status.SIGNED)
        document_id = document.id

        delete_document(document)

        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_signed_path_skips_s3_when_storage_disabled(self, mock_storage: Any, _mock_pandadoc_cls: Any) -> None:
        # Self-hosted / local dev without OBJECT_STORAGE_ENABLED: the helper
        # shouldn't touch object_storage even for signed rows.
        document = self._document(status=LegalDocument.Status.SIGNED)

        delete_document(document)

        mock_storage.delete.assert_not_called()

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_unsigned_without_envelope_id_skips_pandadoc(self, _mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # PandaDoc create may have failed during the original flow, leaving
        # pandadoc_document_id blank. Nothing to void; don't even instantiate
        # the client.
        document = self._document(pandadoc_document_id="")

        delete_document(document)

        mock_pandadoc_cls.assert_not_called()
