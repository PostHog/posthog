from django.urls import URLPattern, path

from posthog.api.routing import RouterRegistry

from products.legal_documents.backend.presentation.views import LegalDocumentViewSet
from products.legal_documents.backend.presentation.webhook import legal_document_pandadoc_webhook

api_urlpatterns: list[URLPattern] = [
    path(
        "pandadoc",
        legal_document_pandadoc_webhook,
        name="legal_document_pandadoc_webhook",
    ),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"legal_documents",
        LegalDocumentViewSet,
        "organization_legal_documents",
        ["organization_id"],
    )
