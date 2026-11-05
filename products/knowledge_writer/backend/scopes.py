"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="knowledge_writer",
        name="Knowledge writer",
        plural="knowledge writer verdicts",
        description="Reporting merged commits to the knowledge writer, which drafts docs changes from them.",
        group="Developer experience",
    ),
)
