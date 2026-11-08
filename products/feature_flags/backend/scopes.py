"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="feature_flag",
        name="Feature flag",
        plural="feature flags",
        description="Feature flags, including their release conditions, variants, payloads, and rollout history.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/feature-flags",
    ),
)
