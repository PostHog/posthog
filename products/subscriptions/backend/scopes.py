"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="subscription",
        name="Subscription",
        plural="subscriptions",
        description="Scheduled email and Slack subscriptions to insights and dashboards, including their delivery history.",
        group="Product analytics",
        docs_url="https://posthog.com/docs/product-analytics/subscriptions",
    ),
)
