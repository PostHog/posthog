"""Curated query builders over the GitHub warehouse snapshots.

``pull_requests`` and ``workflow_runs`` each expose a ``build_query(table_name)``
returning the curated ``SELECT`` over the raw GitHub table whose per-team name is
resolved by ``logic.sources`` and passed in. All PR/CI domain rules (bot detection,
repo identity, label extraction, honest metric naming) are defined here exactly once.
Query modules embed these as subqueries via ``logic.queries._curated`` — nothing is
registered as a global HogQL view.
"""
