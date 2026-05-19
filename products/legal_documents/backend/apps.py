from django.apps import AppConfig


class LegalDocumentsConfig(AppConfig):
    name = "products.legal_documents.backend"
    label = "legal_documents"
    verbose_name = "Legal documents"

    def ready(self) -> None:
        # Register the activity-log signal handler for LegalDocument.
        from . import signals  # noqa: F401
