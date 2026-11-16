"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="experiment",
        name="Experiment",
        plural="experiments",
        description="Experiments and no-code web experiments, including launching, pausing, shipping variants, and results.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/experiments",
    ),
    ScopeDoc(
        object="experiment_holdout",
        name="Holdout",
        plural="holdouts",
        description="Experiment holdouts, the groups of users kept out of experiments to measure their combined impact.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/experiments/holdouts",
    ),
    ScopeDoc(
        object="experiment_saved_metric",
        name="Shared metric",
        plural="shared metrics",
        description="Shared experiment metrics that can be reused across experiments.",
        group="Feature flags, experiments & surveys",
        docs_url="https://posthog.com/docs/experiments/metrics",
    ),
)
