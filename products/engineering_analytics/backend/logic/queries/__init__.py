"""HogQL queries for engineering_analytics.

Each module embeds the curated query builders (``backend/logic/views``) as subqueries via ``_curated``
and runs them with ``execute_hogql_query`` — the product reads privately, never registering a global
view. Raw ``github_*`` tables are named only inside the curated builders; everything returned here is
shaped into canonical contract types.
"""
