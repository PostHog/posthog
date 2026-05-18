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

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_voids_pandadoc_envelope_and_removes_row(self, mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        document = self._document()
        document_id = document.id

        delete_document(document)

        mock_pandadoc_cls.return_value.delete_document.assert_called_once_with(document_id="doc_123")
        mock_storage.delete.assert_called_once()
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_pandadoc_failure_does_not_block_row_delete(self, _mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # PandaDoc unreachable / locked envelope / etc. — we still delete the
        # row so the customer isn't stuck with an undeletable record. The
        # envelope lingers on PandaDoc but is now disconnected from PostHog.
        mock_pandadoc_cls.return_value.delete_document.side_effect = pandadoc_module.PandaDocError("boom")
        document = self._document()
        document_id = document.id

        delete_document(document)

        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_s3_failure_does_not_block_row_delete(self, mock_storage: Any, _mock_pandadoc_cls: Any) -> None:
        mock_storage.delete.side_effect = RuntimeError("s3 down")
        document = self._document()
        document_id = document.id

        delete_document(document)

        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_skips_object_storage_when_disabled(self, mock_storage: Any, _mock_pandadoc_cls: Any) -> None:
        # Self-hosted / local dev without OBJECT_STORAGE_ENABLED — the helper
        # shouldn't touch object_storage at all.
        document = self._document()

        delete_document(document)

        mock_storage.delete.assert_not_called()

    @override_settings(OBJECT_STORAGE_ENABLED=True)
    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_skips_pandadoc_void_when_no_envelope_id(self, _mock_storage: Any, mock_pandadoc_cls: Any) -> None:
        # PandaDoc create may have failed during the original flow, leaving
        # pandadoc_document_id blank. Nothing to void; don't even instantiate
        # the client.
        document = self._document(pandadoc_document_id="")

        delete_document(document)

        mock_pandadoc_cls.assert_not_called()
