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
