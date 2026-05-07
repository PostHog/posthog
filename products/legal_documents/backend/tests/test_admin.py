from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import RequestFactory
from django.utils.datastructures import MultiValueDict

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership

from products.legal_documents.backend.admin import LegalDocumentAdmin, LegalDocumentAdminForm
from products.legal_documents.backend.models import LegalDocument
from products.legal_documents.backend.storage import signed_pdf_storage_key

_VALID_PDF_BYTES = b"%PDF-1.4\nfake pdf bytes for testing\n%%EOF"


def _pdf_file(name: str = "agreement.pdf", content: bytes = _VALID_PDF_BYTES) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def _files(pdf: UploadedFile | None = None) -> MultiValueDict[str, UploadedFile]:
    """Build the typed MultiValueDict the form constructor expects."""
    mvd: MultiValueDict[str, UploadedFile] = MultiValueDict()
    if pdf is not None:
        mvd["signed_pdf"] = pdf
    return mvd


class TestLegalDocumentAdminForm(APIBaseTest):
    def _form_data(self, **overrides: Any) -> dict[str, Any]:
        data = {
            "organization": str(self.organization.id),
            "document_type": "DPA",
            "company_name": "Acme, Inc.",
            "company_address": "1 Analytics Way, SF CA",
            "representative_email": "ada@acme.example",
        }
        data.update(overrides)
        return data

    def test_valid_pdf_passes_validation(self) -> None:
        form = LegalDocumentAdminForm(data=self._form_data(), files=_files(_pdf_file()))
        self.assertTrue(form.is_valid(), form.errors)

    def test_non_pdf_extension_is_rejected(self) -> None:
        bad_file = SimpleUploadedFile("agreement.txt", b"not a pdf", content_type="text/plain")
        form = LegalDocumentAdminForm(data=self._form_data(), files=_files(bad_file))
        self.assertFalse(form.is_valid())
        self.assertIn("signed_pdf", form.errors)

    def test_wrong_content_type_is_rejected(self) -> None:
        # .pdf extension passes the FileExtensionValidator, but if the browser
        # reports a non-application/pdf content type the form should still reject.
        bad_file = SimpleUploadedFile("agreement.pdf", _VALID_PDF_BYTES, content_type="image/png")
        form = LegalDocumentAdminForm(data=self._form_data(), files=_files(bad_file))
        self.assertFalse(form.is_valid())
        self.assertIn("signed_pdf", form.errors)

    def test_oversized_pdf_is_rejected(self) -> None:
        # 26 MiB — over the 25 MiB cap.
        oversized = SimpleUploadedFile("big.pdf", b"x" * (26 * 1024 * 1024), content_type="application/pdf")
        form = LegalDocumentAdminForm(data=self._form_data(), files=_files(oversized))
        self.assertFalse(form.is_valid())
        self.assertIn("signed_pdf", form.errors)

    def test_missing_pdf_is_rejected(self) -> None:
        form = LegalDocumentAdminForm(data=self._form_data(), files=_files())
        self.assertFalse(form.is_valid())
        self.assertIn("signed_pdf", form.errors)


class TestLegalDocumentAdminSave(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.admin = LegalDocumentAdmin(LegalDocument, AdminSite())
        self.request_factory = RequestFactory()

    def _request(self) -> Any:
        request = self.request_factory.post("/admin/posthog/legaldocument/add/")
        request.user = self.user
        return request

    def _bound_form(self, document_type: str = "DPA") -> LegalDocumentAdminForm:
        form = LegalDocumentAdminForm(
            data={
                "organization": str(self.organization.id),
                "document_type": document_type,
                "company_name": "Acme, Inc.",
                "company_address": "1 Analytics Way, SF CA",
                "representative_email": "ada@acme.example",
            },
            files=_files(_pdf_file()),
        )
        self.assertTrue(form.is_valid(), form.errors)
        return form

    @parameterized.expand([("DPA",), ("BAA",), ("MSA",)])
    @patch("products.legal_documents.backend.admin.slack_notifier.notify_admin_uploaded")
    @patch("products.legal_documents.backend.admin.object_storage")
    def test_admin_upload_creates_signed_row_and_writes_to_s3(
        self, document_type: str, mock_storage: Any, mock_slack: Any
    ) -> None:
        form = self._bound_form(document_type=document_type)
        instance = form.save(commit=False)

        self.admin.save_model(self._request(), instance, form, change=False)

        row = LegalDocument.objects.get(id=instance.id)
        self.assertEqual(row.document_type, document_type)
        self.assertEqual(row.status, LegalDocument.Status.SIGNED)
        self.assertEqual(row.created_by_id, self.user.id)
        self.assertEqual(row.organization_id, self.organization.id)

        mock_storage.write_stream.assert_called_once()
        write_args, write_kwargs = mock_storage.write_stream.call_args
        # Key matches the canonical legal_documents/{id}.pdf shape used by the
        # public download endpoint.
        self.assertTrue(write_args[0].endswith(f"{row.id}.pdf"))
        self.assertEqual(write_kwargs.get("extras"), {"ContentType": "application/pdf"})

        mock_slack.assert_called_once()
        _, slack_kwargs = mock_slack.call_args
        self.assertEqual(slack_kwargs["uploaded_by_email"], self.user.email)

    @patch("products.legal_documents.backend.admin.slack_notifier.notify_admin_uploaded")
    @patch("products.legal_documents.backend.admin.object_storage")
    def test_s3_failure_rolls_back_row(self, mock_storage: Any, mock_slack: Any) -> None:
        mock_storage.write_stream.side_effect = RuntimeError("s3 unreachable")

        form = self._bound_form()
        instance = form.save(commit=False)
        with self.assertRaises(ValidationError):
            self.admin.save_model(self._request(), instance, form, change=False)

        # Row was not persisted — transaction.atomic rolled it back when ValidationError fired.
        self.assertFalse(LegalDocument.objects.filter(id=instance.id).exists())
        # No Slack notification on failure.
        mock_slack.assert_not_called()

    def test_pre_existing_row_blocks_form_validation(self) -> None:
        # Django's ModelForm.validate_unique catches the unique-per-org-per-type
        # constraint at form-validation time, so the admin user sees a clean
        # form error instead of a 500. (save_model also handles IntegrityError
        # as defense in depth for race conditions, but the normal path stops
        # at form.is_valid().)
        LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Already there",
            company_address="elsewhere",
            representative_email="other@acme.example",
            status=LegalDocument.Status.SIGNED,
        )
        form = LegalDocumentAdminForm(
            data={
                "organization": str(self.organization.id),
                "document_type": "DPA",
                "company_name": "Acme, Inc.",
                "company_address": "1 Analytics Way, SF CA",
                "representative_email": "ada@acme.example",
            },
            files=_files(_pdf_file()),
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(LegalDocument.objects.filter(document_type="DPA").count(), 1)

    @patch("products.legal_documents.backend.admin.object_storage")
    def test_delete_model_cleans_up_s3(self, mock_storage: Any) -> None:
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="MSA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
        )
        # Snapshot before delete: obj.delete() clears the pk on the in-memory
        # instance, so signed_pdf_storage_key(document) would compute against
        # id=None afterwards.
        expected_key = signed_pdf_storage_key(document)
        document_id = document.id
        self.admin.delete_model(self._request(), document)

        mock_storage.delete.assert_called_once_with(expected_key)
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    def test_change_view_form_saves_without_signed_pdf(self) -> None:
        # The add form (LegalDocumentAdminForm) declares signed_pdf
        # as a required FileField. If it leaks into the change view's form,
        # "Save" on an existing row fails with "This field is required" even
        # though no upload widget is rendered.
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
        )
        change_form_class = self.admin.get_form(self._request(), obj=document, change=True)

        # The change-view form must not declare signed_pdf. (Plain ModelForm
        # subclass returned by modelform_factory has no extra non-model fields.)
        self.assertNotIn("signed_pdf", change_form_class.base_fields)

    @patch("products.legal_documents.backend.admin.object_storage")
    def test_delete_model_swallows_s3_errors(self, mock_storage: Any) -> None:
        # If S3 cleanup fails the row should still be deleted — best-effort cleanup.
        mock_storage.delete.side_effect = RuntimeError("s3 down")
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="MSA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
        )
        document_id = document.id

        self.admin.delete_model(self._request(), document)

        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())


class TestLegalDocumentAdminPermissions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = LegalDocumentAdmin(LegalDocument, AdminSite())
        self.request_factory = RequestFactory()

    def _request_for(self, *, is_staff: bool) -> Any:
        request = self.request_factory.get("/admin/posthog/legaldocument/")
        self.user.is_staff = is_staff
        self.user.save()
        request.user = self.user
        return request

    def test_staff_can_add_and_delete(self) -> None:
        request = self._request_for(is_staff=True)
        self.assertTrue(self.admin.has_add_permission(request))
        self.assertTrue(self.admin.has_delete_permission(request))

    def test_non_staff_cannot_add_or_delete(self) -> None:
        request = self._request_for(is_staff=False)
        self.assertFalse(self.admin.has_add_permission(request))
        self.assertFalse(self.admin.has_delete_permission(request))
