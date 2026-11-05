"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="export",
        name="Export",
        plural="exports",
        description="Exported files of insights, dashboards, and session recordings, such as PNG, PDF, CSV, and video.",
        group="Product analytics",
    ),
)
