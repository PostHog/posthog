"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDependency, ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="early_access_feature",
        name="Early access feature",
        plural="early access features",
        description="Early access features users can opt into, including their stage and linked feature flag.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/feature-flags/early-access-feature-management",
        write_requires=ScopeDependency(
            scope="feature_flag:write",
            reason="Early access features manage a linked feature flag, so this key needs write access to feature flags too.",
        ),
    ),
)
