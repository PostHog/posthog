"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="code_review_approval",
        name="Code review auto-approval",
        plural="code review auto-approvals",
        description="PostHog Review auto-approval of pull requests, including repository settings, review runs, and reviewer routing.",
        group="Developer experience",
    ),
)
