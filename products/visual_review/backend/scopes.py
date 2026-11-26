"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="visual_review",
        name="Visual review",
        plural="visual reviews",
        description="Visual review repos, CI runs, screenshot snapshots, baselines, approvals, and quarantined snapshots.",
        group="Developer experience",
    ),
)
