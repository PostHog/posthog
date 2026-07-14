"""Synthetic eval project: representative, queryable data for agentic evals.

The agentic steps query a real PostHog project via MCP during a *live* run — research runs
``execute-sql`` / ``list-errors`` / ``insights-get-all`` against the team's data. To give those
tools something meaningful to find, we seed a dedicated eval project with the hedgebox demo
dataset (events, error-tracking issues, insights, feature flags, experiments) — the same
battle-tested generator the product demo uses — plus a manifest tying it to the OSS repo
registry the repo-selection and implementation evals operate on.

This package is the seeding + manifest layer; it is only needed for live/record runs (replay
needs no project). See ``README.md`` and ``seed.py``.
"""
