import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile

from parameterized import parameterized

from products.legal_documents.backend.console import LegalDocumentsPanel
from products.legal_documents.backend.facade.api import upload_signed_document_as_staff
from products.legal_documents.backend.facade.contracts import StaffSignedDocumentUpload
from products.legal_documents.backend.facade.enums import StaffUploadOutcome
from products.legal_documents.backend.models import LegalDocument
from products.legal_documents.backend.storage import signed_pdf_storage_key

_LOGIC = "products.legal_documents.backend.logic"
_PDF_BYTES = b"%PDF-1.4\nfake pdf bytes for testing\n%%EOF"


def _pdf(name: str = "agreement.pdf", content: bytes = _PDF_BYTES, content_type: str = "application/pdf") -> Any:
    return SimpleUploadedFile(name, content, content_type=content_type)


class TestLegalDocumentsConsolePanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _document(self, **overrides: Any) -> LegalDocument:
        fields: dict[str, Any] = {
            "organization": self.organization,
            "document_type": "BAA",
            "company_name": "Acme, Inc.",
            "company_address": "1 Analytics Way",
            "representative_email": "ada@acme.example",
            "status": LegalDocument.Status.SIGNED,
            "pandadoc_document_id": "doc_123",
        }
        fields.update(overrides)
        return LegalDocument.objects.create(**fields)

    def _post(self, operation_key: str, data: dict[str, Any]) -> Any:
        return self.client.post(
            f"/admin/console/organizations/{self.organization.pk}/legal-documents/{operation_key}/", data
        )

    def _offered(self) -> set[str]:
        return {operation.key for operation in LegalDocumentsPanel().operations(self.organization)}

    @parameterized.expand(
        [
            ("signed_with_envelope", {}, {"upload-signed-document", "refetch-pdf", "delete"}),
            (
                "out_for_signature",
                {"status": LegalDocument.Status.SUBMITTED_FOR_SIGNATURE},
                {"upload-signed-document", "resend-signing-email", "delete"},
            ),
            ("signed_without_envelope", {"pandadoc_document_id": ""}, {"upload-signed-document", "delete"}),
            (
                "out_for_signature_without_envelope",
                {"status": LegalDocument.Status.SUBMITTED_FOR_SIGNATURE, "pandadoc_document_id": ""},
                {"upload-signed-document", "delete"},
            ),
        ]
    )
    def test_offers_only_what_pandadoc_can_do_for_the_document(
        self, _name: str, overrides: dict[str, Any], expected: set[str]
    ) -> None:
        self._document(**overrides)

        assert self._offered() == expected

    def test_organization_without_documents_offers_only_the_upload(self) -> None:
        assert self._offered() == {"upload-signed-document"}

    def test_organization_with_every_document_type_offers_no_upload(self) -> None:
        for document_type in ("BAA", "DPA", "MSA"):
            self._document(document_type=document_type, pandadoc_document_id="")

        assert self._offered() == {"delete"}

    def _upload_data(self, pdf: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "document_type": "MSA",
            "company_name": "Acme, Inc.",
            "company_address": "1 Analytics Way",
            "representative_email": "ada@acme.example",
        }
        if pdf is not None:
            data["signed_pdf"] = pdf
        return data

    @patch(f"{_LOGIC}.object_storage")
    def test_upload_saves_a_signed_row_and_its_pdf(self, mock_storage: MagicMock) -> None:
        response = self._post("upload-signed-document", self._upload_data(_pdf()))

        assert response.status_code == 302
        document = LegalDocument.objects.get(organization=self.organization, document_type="MSA")
        assert document.status == LegalDocument.Status.SIGNED
        assert document.signed_pdf_stored
        assert document.created_by_id == self.user.id
        mock_storage.write_stream.assert_called_once()
        key, _stream = mock_storage.write_stream.call_args.args
        assert key == signed_pdf_storage_key(document)
        assert mock_storage.write_stream.call_args.kwargs["extras"] == {"ContentType": "application/pdf"}

    @patch(f"{_LOGIC}.object_storage")
    def test_upload_of_a_baa_opts_the_organization_out_of_ai(self, _mock_storage: MagicMock) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.is_ai_training_opted_in = True
        self.organization.save()

        response = self._post("upload-signed-document", {**self._upload_data(_pdf()), "document_type": "BAA"})

        assert response.status_code == 302
        self.organization.refresh_from_db()
        assert self.organization.is_ai_data_processing_approved is False
        assert self.organization.is_ai_training_opted_in is False

    @patch(f"{_LOGIC}.object_storage")
    def test_upload_storage_failure_saves_no_row(self, mock_storage: MagicMock) -> None:
        mock_storage.write_stream.side_effect = RuntimeError("s3 unreachable")

        response = self._post("upload-signed-document", self._upload_data(_pdf()))

        assert response.status_code == 502
        assert not LegalDocument.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            ("missing", lambda: None),
            ("not_a_pdf_extension", lambda: _pdf(name="agreement.txt", content_type="text/plain")),
            ("not_a_pdf_content_type", lambda: _pdf(content_type="image/png")),
            ("oversized", lambda: _pdf(content=b"x" * (26 * 1024 * 1024))),
        ]
    )
    @patch(f"{_LOGIC}.object_storage")
    def test_upload_refuses_a_file_that_is_not_the_signed_pdf(
        self, _name: str, make_pdf: Callable[[], Any], mock_storage: MagicMock
    ) -> None:
        response = self._post("upload-signed-document", self._upload_data(make_pdf()))

        assert response.status_code == 400
        mock_storage.write_stream.assert_not_called()
        assert not LegalDocument.objects.filter(organization=self.organization).exists()

    @patch(f"{_LOGIC}.object_storage")
    def test_upload_of_a_type_the_organization_already_has_is_refused(self, mock_storage: MagicMock) -> None:
        # The form lists only free types, so this is the race where another upload lands first.
        self._document(document_type="MSA")
        upload = StaffSignedDocumentUpload(
            organization_id=self.organization.pk,
            created_by_id=self.user.pk,
            document_type="MSA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
        )

        assert upload_signed_document_as_staff(upload, _pdf()) == StaffUploadOutcome.ALREADY_EXISTS
        assert LegalDocument.objects.filter(organization=self.organization, document_type="MSA").count() == 1

    @patch(f"{_LOGIC}.download_and_store_signed_pdf", return_value=True)
    def test_refetch_stores_the_pandadoc_pdf_and_marks_the_row_stored(self, mock_download: MagicMock) -> None:
        document = self._document(signed_pdf_stored=False)

        response = self._post("refetch-pdf", {"document": str(document.id), "reason": "Counter-signed copy"})

        assert response.status_code == 302
        mock_download.assert_called_once()
        document.refresh_from_db()
        assert document.signed_pdf_stored

    @patch(f"{_LOGIC}.download_and_store_signed_pdf", return_value=False)
    def test_refetch_failure_leaves_the_stored_copy_alone(self, _mock_download: MagicMock) -> None:
        document = self._document(signed_pdf_stored=False)

        response = self._post("refetch-pdf", {"document": str(document.id), "reason": "Counter-signed copy"})

        assert response.status_code == 502
        assert "Could not refetch" in " ".join(str(message) for message in get_messages(response.wsgi_request))
        document.refresh_from_db()
        assert not document.signed_pdf_stored

    @patch(f"{_LOGIC}.download_and_store_signed_pdf")
    def test_refetch_refuses_a_document_pandadoc_cannot_serve(self, mock_download: MagicMock) -> None:
        # A PDF pulled for anything but a completed envelope would land behind the customer-facing download link
        # as if it were the signed document. The form only lists refetchable documents, so another one is refused.
        self._document(document_type="DPA")
        unsigned = self._document(status=LegalDocument.Status.SUBMITTED_FOR_SIGNATURE)

        response = self._post("refetch-pdf", {"document": str(unsigned.id), "reason": "Counter-signed copy"})

        assert response.status_code == 400
        mock_download.assert_not_called()

    @patch(f"{_LOGIC}.pandadoc_client.PandaDocClient")
    def test_resend_sends_the_envelope_of_the_selected_document(self, mock_pandadoc_cls: MagicMock) -> None:
        stranded = self._document(
            status=LegalDocument.Status.SUBMITTED_FOR_SIGNATURE, pandadoc_document_id="doc_stranded"
        )

        response = self._post("resend-signing-email", {"document": str(stranded.id)})

        assert response.status_code == 302
        mock_pandadoc_cls.return_value.send_document.assert_called_once()
        assert mock_pandadoc_cls.return_value.send_document.call_args.kwargs["document_id"] == "doc_stranded"

    @parameterized.expand(
        [
            # A completed envelope cannot be voided, so a signed delete only removes the stored PDF.
            ("signed", LegalDocument.Status.SIGNED, "doc_123", False, True),
            # An unsigned row has no PDF yet, and its envelope is voided so the signer cannot complete it.
            ("out_for_signature", LegalDocument.Status.SUBMITTED_FOR_SIGNATURE, "doc_123", True, False),
            ("no_envelope", LegalDocument.Status.SIGNED, "", False, True),
        ]
    )
    @patch(f"{_LOGIC}.pandadoc_client.PandaDocClient")
    @patch(f"{_LOGIC}.object_storage")
    def test_delete_cleans_up_pandadoc_and_storage_by_status(
        self,
        _name: str,
        status: str,
        pandadoc_document_id: str,
        expect_void: bool,
        expect_storage_delete: bool,
        mock_storage: MagicMock,
        mock_pandadoc_cls: MagicMock,
    ) -> None:
        document = self._document(status=status, pandadoc_document_id=pandadoc_document_id)
        storage_key = signed_pdf_storage_key(document)

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self._post("delete", {"document": str(document.id), "reason": "Customer asked for a new BAA"})

        assert response.status_code == 302
        assert not LegalDocument.objects.filter(id=document.id).exists()
        assert mock_pandadoc_cls.return_value.void_document.called == expect_void
        if expect_storage_delete:
            mock_storage.delete.assert_called_once_with(storage_key)
        else:
            mock_storage.delete.assert_not_called()

    @patch(f"{_LOGIC}.pandadoc_client.PandaDocClient")
    @patch(f"{_LOGIC}.object_storage")
    def test_delete_still_deletes_the_row_when_storage_fails(
        self, mock_storage: MagicMock, _mock_pandadoc_cls: MagicMock
    ) -> None:
        mock_storage.delete.side_effect = RuntimeError("s3 down")
        document = self._document(pandadoc_document_id="")

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            self._post("delete", {"document": str(document.id), "reason": "Duplicate"})

        assert not LegalDocument.objects.filter(id=document.id).exists()

    def test_delete_needs_a_reason(self) -> None:
        document = self._document()

        response = self._post("delete", {"document": str(document.id)})

        assert response.status_code == 400
        assert LegalDocument.objects.filter(id=document.id).exists()

    @parameterized.expand(
        [
            ("refetch", "get", "refetch-pdf", str, "?from=bookmark&document={id}#panel-legal-documents"),
            ("delete", "get", "delete", str, "legal-documents/delete/?from=bookmark&document={id}"),
            # Django admin reads each of these spellings as the same document, so each must miss its delete view.
            (
                "delete_uppercase",
                "post",
                "delete",
                lambda id: str(id).upper(),
                "legal-documents/delete/?from=bookmark&document={id}",
            ),
            (
                "delete_without_hyphens",
                "post",
                "delete",
                lambda id: id.hex,
                "legal-documents/delete/?from=bookmark&document={id}",
            ),
            (
                "delete_admin_quoted",
                "post",
                "delete",
                lambda id: f"urn_3Auuid_3A{id}",
                "legal-documents/delete/?from=bookmark&document={id}",
            ),
        ]
    )
    def test_the_old_document_url_lands_in_the_console_of_the_document_organization(
        self, _name: str, method: str, old_path: str, spell_id: Callable[[UUID], str], target: str
    ) -> None:
        document = self._document()

        url = f"/admin/legal_documents/legaldocument/{spell_id(document.id)}/{old_path}/?from=bookmark"

        # The POST is the confirm submit of the admin delete page, which would delete the row.
        response = self.client.post(url, {"post": "yes"}) if method == "post" else self.client.get(url)

        assert response.status_code == 302
        expected = target.format(id=document.id)
        assert response["Location"] == f"/admin/console/organizations/{self.organization.pk}/{expected}"
        assert LegalDocument.objects.filter(id=document.id).exists()

    def test_an_old_delete_url_without_a_document_id_is_not_found(self) -> None:
        document = self._document()

        response = self.client.post("/admin/legal_documents/legaldocument/not-a-uuid/delete/", {"post": "yes"})

        assert response.status_code == 404
        assert LegalDocument.objects.filter(id=document.id).exists()

    def test_the_delete_form_preselects_the_document_the_old_url_named(self) -> None:
        self._document()
        older = self._document(document_type="DPA")

        form = self.client.get(
            f"/admin/console/organizations/{self.organization.pk}/legal-documents/delete/?document={older.id}"
        ).content.decode()

        assert re.search(rf'<option value="{older.id}"\s+selected>', form)
