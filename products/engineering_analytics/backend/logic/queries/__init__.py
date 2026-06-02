"""HogQL queries for engineering_analytics.

These read the curated read layer (``engineering_analytics_pull_requests``,
``engineering_analytics_workflow_runs``) by name — never the raw ``github_*``
warehouse tables, which are named only in ``backend/logic/views``. Everything here
works with canonical contract types.
"""
