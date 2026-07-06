"""Declarative spec of the synthetic eval project.

Single source of truth for *what* the eval project contains and which OSS repos are wired
in as repo-selection candidates. Pure data so it can be imported and tested without a stack,
and so the seeding command and the docs never drift from each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from products.signals.eval.agentic.repos import REGISTRY

# Default identity for the eval project. A stable seed makes the hedgebox simulation
# reproducible across re-seeds, so eval baselines move only when the agent or prompts change.
DEFAULT_SEED = "signals-agentic-eval"
DEFAULT_PRODUCT = "hedgebox"
DEFAULT_N_CLUSTERS = 40


@dataclass(frozen=True)
class EvalProjectManifest:
    """The shape of the seeded eval project."""

    seed: str = DEFAULT_SEED
    product: str = DEFAULT_PRODUCT
    n_clusters: int = DEFAULT_N_CLUSTERS
    # OSS repos exposed as repo-selection candidates (full_name, lowercased).
    candidate_repos: tuple[str, ...] = field(default_factory=lambda: tuple(r.full_name for r in REGISTRY.values()))

    # What hedgebox seeds that the research agent can query via MCP. Documented here so reviewers
    # know what data the live evals depend on (see posthog/demo/products/hedgebox/matrix.py).
    # Observed on a local seed (team 1) on 2026-06-27 — a representative mix the agent can analyze:
    seeded_data: tuple[str, ...] = (
        "Analytics: ~78 distinct event types (downloaded_file, uploaded_file, signed_up, paid_bill, "
        "$pageview, $feature_flag_called, $web_vitals, react_framerate …) over months of history",
        "Error tracking: ~62 issues incl. Checkout API timeout, File preview render failure, Team invite "
        "rejected, plus $exception events",
        "Session replays: ~37 recorded sessions (queryable via session-replay tools)",
        "Insights (~17) and dashboards (~5): key metrics, revenue, website",
        "Feature flags and experiments in varied states (Pricing page redesign, File engagement boost, "
        "Onboarding flow test, File sharing incentive)",
        "Data-warehouse tables (paid_bills, signups, uploaded_files, plan_changes) and an 'account' group type",
    )

    # Signal source_products the eval cases exercise — the 'external signals from sources' the inbox
    # ingests. Cases vary these to mirror real signal provenance.
    signal_sources: tuple[str, ...] = (
        "error_tracking",
        "session_replay",
        "github",
        "linear",
        "zendesk",
        "conversations",
    )


DEFAULT_MANIFEST = EvalProjectManifest()
