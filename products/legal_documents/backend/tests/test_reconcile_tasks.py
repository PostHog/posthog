from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from django.test import SimpleTestCase

from posthog.celery import app

from products.legal_documents.backend.facade import api as legal_api
from products.legal_documents.backend.tasks.tasks import archive_signed_legal_document_pdf


class TestArchiveSignedLegalDocumentPdfRetryConfig(SimpleTestCase):
    def test_registered_under_pinned_name(self) -> None:
        # facade/tasks.py re-exports this task by name rather than import path, so a
        # rename that drops registration under the pinned name would silently break
        # that lookup. Suffix match tolerates the pinned name's prefix changing.
        assert archive_signed_legal_document_pdf.name.endswith("archive_signed_legal_document_pdf")
        assert archive_signed_legal_document_pdf.name in app.tasks

    def test_retry_config_is_not_inert(self) -> None:
        # Bare max_retries without autoretry_for is silently inert; assert the wiring
        # this task's whole purpose depends on is actually there.
        assert archive_signed_legal_document_pdf.autoretry_for == (legal_api.LegalDocumentPdfArchiveFailed,)
        assert archive_signed_legal_document_pdf.max_retries == 8
        assert archive_signed_legal_document_pdf.retry_backoff == 30
        assert archive_signed_legal_document_pdf.retry_backoff_max == 600
        assert archive_signed_legal_document_pdf.retry_jitter is True


class BackfillSignedPdfStoredMigrationTest(NonAtomicTestMigrations):
    """0006 marks pre-existing signed rows as archived. The old flow only flipped
    status to `signed` after the PDF was already written to object storage, so every
    row signed before this migration has its PDF sitting in storage already. The
    reconciliation sweep only looks at signed_pdf_stored=False rows, so an unmarked
    signed row would get silently re-swept and would hide its download link.
    """

    migrate_from = "0005_legaldocument_signed_pdf_stored"
    migrate_to = "0006_backfill_signed_pdf_stored"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "legal_documents"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        LegalDocument = apps.get_model("legal_documents", "LegalDocument")

        org = Organization.objects.create(name="Acme, Inc.")
        self.signed_id = LegalDocument.objects.create(
            organization=org,
            document_type="BAA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status="signed",
        ).id
        self.pending_id = LegalDocument.objects.create(
            organization=org,
            document_type="DPA",
            company_name="Acme, Inc.",
            company_address="1 Analytics Way",
            representative_email="ada@acme.example",
            status="submitted_for_signature",
        ).id

    def test_backfills_signed_rows_only(self) -> None:
        LegalDocument = self.apps.get_model("legal_documents", "LegalDocument")  # type: ignore[union-attr]

        assert LegalDocument.objects.get(id=self.signed_id).signed_pdf_stored is True
        assert LegalDocument.objects.get(id=self.pending_id).signed_pdf_stored is False
