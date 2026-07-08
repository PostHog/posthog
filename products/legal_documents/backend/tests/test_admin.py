from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.admin.widgets import AutocompleteSelect
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import RequestFactory
from django.utils.datastructures import MultiValueDict

from parameterized import parameterized

from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.models.organization import Organization, OrganizationMembership

from products.legal_documents.backend.admin import LegalDocumentAdmin, LegalDocumentAdminForm, LegalDocumentInline
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
    @patch("products.legal_documents.backend.admin.object_storage")
    def test_admin_upload_creates_signed_row_and_writes_to_s3(self, document_type: str, mock_storage: Any) -> None:
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

    @patch("products.legal_documents.backend.admin.object_storage")
    def test_s3_failure_rolls_back_row(self, mock_storage: Any) -> None:
        mock_storage.write_stream.side_effect = RuntimeError("s3 unreachable")

        form = self._bound_form()
        instance = form.save(commit=False)
        with self.assertRaises(ValidationError):
            self.admin.save_model(self._request(), instance, form, change=False)

        # Row was not persisted — transaction.atomic rolled it back when ValidationError fired.
        self.assertFalse(LegalDocument.objects.filter(id=instance.id).exists())

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

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_delete_model_for_signed_row_cleans_up_s3_and_skips_pandadoc(
        self, mock_storage: Any, mock_pandadoc_cls: Any
    ) -> None:
        # Signed rows have a PDF in S3 (PandaDoc completion webhook stashed it,
        # or admin uploaded it) and a completed envelope on PandaDoc that can't
        # be voided. Helper deletes the S3 object and skips the PandaDoc call.
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="MSA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
            pandadoc_document_id="doc_123",
        )
        # Snapshot before delete: obj.delete() clears the pk on the in-memory
        # instance, so signed_pdf_storage_key(document) would compute against
        # id=None afterwards.
        expected_key = signed_pdf_storage_key(document)
        document_id = document.id
        self.admin.delete_model(self._request(), document)

        mock_storage.delete.assert_called_once_with(expected_key)
        mock_pandadoc_cls.assert_not_called()
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_delete_model_for_unsigned_row_voids_pandadoc_and_skips_s3(
        self, mock_storage: Any, mock_pandadoc_cls: Any
    ) -> None:
        # Unsigned rows have an in-flight PandaDoc envelope that should be
        # voided so the original recipient can't still complete it. No PDF
        # exists in S3 until completion, so the S3 call is skipped.
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SUBMITTED_FOR_SIGNATURE,
            pandadoc_document_id="doc_123",
        )
        document_id = document.id
        self.admin.delete_model(self._request(), document)

        mock_pandadoc_cls.return_value.void_document.assert_called_once_with(document_id="doc_123")
        mock_storage.delete.assert_not_called()
        self.assertFalse(LegalDocument.objects.filter(id=document_id).exists())

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_delete_model_skips_pandadoc_void_when_no_envelope_id(
        self, _mock_storage: Any, mock_pandadoc_cls: Any
    ) -> None:
        # If the row was never bound to a PandaDoc envelope (e.g., admin-uploaded
        # MSA, or PandaDoc create failed during the original flow) there's
        # nothing to void — the client shouldn't even be instantiated.
        document = LegalDocument.objects.create(
            organization=self.organization,
            document_type="MSA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SIGNED,
            pandadoc_document_id="",
        )
        self.admin.delete_model(self._request(), document)
        mock_pandadoc_cls.assert_not_called()

    def test_add_form_uses_autocomplete_for_organization(self) -> None:
        # The organization FK must render an autocomplete widget, not the default
        # <select> — the latter loads every org row into the page and times out
        # the add view on Cloud.
        add_form_class = self.admin.get_form(self._request(), obj=None, change=False)
        widget = add_form_class.base_fields["organization"].widget
        # Admin wraps FK widgets in RelatedFieldWidgetWrapper (the +add/edit links).
        inner = getattr(widget, "widget", widget)
        self.assertIsInstance(inner, AutocompleteSelect)

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

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_delete_model_swallows_s3_errors(self, mock_storage: Any, _mock_pandadoc_cls: Any) -> None:
        # If S3 cleanup fails the row should still be deleted — best-effort cleanup.
        # PandaDocClient is patched as defense-in-depth so this test never makes
        # a real network call if the fixture sprouts a pandadoc_document_id.
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

    @patch("products.legal_documents.backend.logic.pandadoc_client.PandaDocClient")
    @patch("products.legal_documents.backend.logic.object_storage")
    def test_delete_queryset_fires_per_row_pandadoc_voids_and_deletes_rows(
        self, _mock_storage: Any, mock_pandadoc_cls: Any
    ) -> None:
        # Bulk delete via the changelist must call the shared logic helper
        # once per row (not queryset.delete()) so each envelope gets voided
        # individually and each row fires its own activity-log entry.
        other_org = type(self.organization).objects.create(name="Other Co")
        first = LegalDocument.objects.create(
            organization=self.organization,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status=LegalDocument.Status.SUBMITTED_FOR_SIGNATURE,
            pandadoc_document_id="doc_111",
        )
        second = LegalDocument.objects.create(
            organization=other_org,
            document_type="DPA",
            company_name="Other Co",
            company_address="Elsewhere",
            representative_email="bob@other.example",
            status=LegalDocument.Status.SUBMITTED_FOR_SIGNATURE,
            pandadoc_document_id="doc_222",
        )

        queryset = LegalDocument.objects.filter(id__in=[first.id, second.id])
        self.admin.delete_queryset(self._request(), queryset)

        # Two distinct PandaDoc void calls, one per row.
        self.assertEqual(mock_pandadoc_cls.return_value.void_document.call_count, 2)
        called_ids = {
            call.kwargs["document_id"] for call in mock_pandadoc_cls.return_value.void_document.call_args_list
        }
        self.assertEqual(called_ids, {"doc_111", "doc_222"})
        self.assertFalse(LegalDocument.objects.filter(id__in=[first.id, second.id]).exists())


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


class TestLegalDocumentInlineRegistration(APIBaseTest):
    def test_inline_attaches_to_organization_admin(self) -> None:
        # legal_documents registers LegalDocumentInline via posthog.admin.inline_registry, so
        # core surfaces it on the Organization admin page without importing the product.
        org_admin = OrganizationAdmin(Organization, AdminSite())
        inlines = org_admin.get_inlines(RequestFactory().get("/"))
        self.assertIn(LegalDocumentInline, inlines)
        # It arrived through the registry, not core's static inlines list.
        self.assertNotIn(LegalDocumentInline, org_admin.inlines)
