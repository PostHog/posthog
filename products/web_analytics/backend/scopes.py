"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="heatmap",
        name="Heatmap",
        plural="heatmaps",
        description="Click and scroll heatmap data, page screenshots, and saved heatmaps.",
        group="Web, marketing & revenue analytics",
        docs_url="https://posthog.com/docs/toolbar/heatmaps",
    ),
    ScopeDoc(
        object="web_analytics",
        name="Web analytics",
        plural="web analytics",
        description="Web analytics digests, bot rules, path cleaning suggestions, achievements, and AI search prompts.",
        group="Web, marketing & revenue analytics",
        docs_url="https://posthog.com/docs/web-analytics",
    ),
)
