"""Inbox "plan mode" — the Projects surface.

A plan report ("project") is a `SignalReport` distinguished by its backing `inbox`/`plan` signal.
This package holds the read surface for that tab: a ClickHouse lookup of the plan signals
(`queries.py`) enriched with the report rows from Postgres, exposed through the custom
`InboxPlan*` viewsets (`views.py`). See `products/signals/backend/plan.md` for the wider design.
"""
