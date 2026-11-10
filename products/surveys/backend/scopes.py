"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDependency, ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="survey",
        name="Survey",
        plural="surveys",
        description="Surveys, including their questions, targeting, responses, stats, and launch status.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/surveys",
        write_requires=ScopeDependency(
            scope="feature_flag:write",
            reason="Surveys with targeting also manage a feature flag, so this key needs write access to feature flags too.",
        ),
    ),
)
