"""Curated query builders over the GitHub warehouse snapshots.

``pull_requests`` and ``workflow_runs`` each expose ``build_query(table_name)`` returning the curated
``SELECT`` over the raw GitHub table (per-team name resolved by ``logic.sources``). All PR/CI domain
rules (bot detection, repo identity, labels, honest metric naming) live here exactly once. Query
modules embed these as subqueries via ``logic.queries._curated``; nothing is a global HogQL view.
"""
