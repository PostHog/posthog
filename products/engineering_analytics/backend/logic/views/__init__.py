"""Curated query builders over the GitHub warehouse snapshots.

``pull_requests`` and ``workflow_runs`` each expose a ``build_query()`` returning
the curated ``SELECT`` over the raw ``github_*`` table. All PR/CI domain rules
(bot detection, repo identity, label extraction, honest metric naming) are
defined here exactly once. Query modules embed these as subqueries via
``logic.queries._curated`` — nothing is registered as a global HogQL view.
"""
