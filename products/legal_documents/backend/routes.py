from posthog.api.routing import RouterRegistry

from products.legal_documents.backend.presentation.views import DesktopBetaTermsViewSet, LegalDocumentViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"desktop_beta_terms",
        DesktopBetaTermsViewSet,
        "organization_desktop_beta_terms",
        ["organization_id"],
    )
    routers.organizations.register(
        r"legal_documents",
        LegalDocumentViewSet,
        "organization_legal_documents",
        ["organization_id"],
    )
