"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="hog_flow",
        name="Workflow",
        plural="workflows",
        description="Workflows and messaging, including email templates, message categories, opt-outs, and suppression lists.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/workflows",
    ),
)
