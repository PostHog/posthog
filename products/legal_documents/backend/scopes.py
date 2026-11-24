"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="legal_document",
        name="Legal document",
        plural="legal documents",
        description="Your organization's BAA and DPA documents, including requesting, downloading, and deleting them.",
        group="Organization & account",
        docs_url="https://posthog.com/docs/privacy",
    ),
)
