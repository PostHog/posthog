"""Seed the synthetic eval project.

Delegates the heavy lifting to the production ``generate_demo_data`` command (hedgebox) so we
reuse a battle-tested, representative dataset rather than reimplementing event emission. This
requires the local stack (Postgres + ClickHouse + Kafka); it is a live-mode prerequisite, not
something replay needs.
"""

from __future__ import annotations

import logging
import datetime as dt

from products.signals.eval.agentic.project.manifest import DEFAULT_MANIFEST, EvalProjectManifest

logger = logging.getLogger(__name__)

# Without a pinned "now" a re-seed shifts every timestamp and drifts from the committed
# ground truth; 2026-06-27 matches the seed the manifest was observed on.
SIMULATION_NOW = dt.datetime(2026, 6, 27, 12, 0, 0, tzinfo=dt.UTC)


def seed_eval_project(
    *,
    team_id: int | None = None,
    manifest: EvalProjectManifest = DEFAULT_MANIFEST,
) -> None:
    """Seed (or re-seed) the eval project's analytics + error-tracking data.

    With ``team_id`` the data is seeded into that existing project; without it a fresh demo
    org/user/project is created and its credentials printed by ``generate_demo_data``. The
    deterministic ``seed`` plus the pinned ``SIMULATION_NOW`` keep the simulation reproducible
    across re-seeds regardless of when they run.
    """
    from django.core.management import call_command  # noqa: PLC0415 — Django entrypoint, lazy by design

    kwargs: dict[str, object] = {
        "product": manifest.product,
        "seed": manifest.seed,
        "n_clusters": manifest.n_clusters,
        "now": SIMULATION_NOW,
    }
    if team_id is not None:
        kwargs["team_id"] = team_id
    logger.info("seeding eval project via generate_demo_data %s", kwargs)
    call_command("generate_demo_data", **kwargs)
