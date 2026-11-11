"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="endpoint",
        name="Endpoint",
        plural="endpoints",
        description="Endpoints, saved queries served as API routes, including runs, versions, materialization, and OpenAPI specs.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/endpoints",
    ),
)
