"""
Utility functions for LLMA daily metrics aggregation.
"""

from pathlib import Path

from jinja2 import Template

from products.llm_analytics.dags.daily_metrics.config import config

# SQL template directory
SQL_DIR = Path(__file__).parent / "sql"

# Metric types to include (matches SQL filenames without .sql extension)
# Set to None to include all, or list specific ones to include
ENABLED_METRICS: list[str] | None = None  # or ["event_counts", "error_rates"]


def get_llma_events_cte(metric_date: str) -> str:
    """
    Generate CTEs that pre-filter events to only relevant teams for a single day.

    This two-step approach (first find teams, then filter events) allows ClickHouse
    to use the sorting key (team_id, toDate(timestamp)) more efficiently.

    Uses SAMPLE 0.1 (10%) as a safety mechanism to limit query scope.
    TODO: Remove SAMPLE once query performance is validated in production.

    Args:
        metric_date: The date to aggregate metrics for (YYYY-MM-DD format)

    Provides:
    - llma_events: AI events filtered to teams with AI activity
    - llma_pageview_events: Pageview events filtered to teams viewing LLM analytics pages
    """
    event_types_sql = ", ".join(f"'{et}'" for et in config.ai_event_types)
    url_patterns_sql = " OR ".join(
        f"JSONExtractString(properties, '$current_url') LIKE '%{url_path}%'" for url_path, _ in config.pageview_mappings
    )

    return f"""teams_with_ai_events AS (
    SELECT DISTINCT team_id
    FROM events SAMPLE 0.1
    WHERE event IN ({event_types_sql})
      AND toDate(timestamp) = '{metric_date}'
),
llma_events AS (
    SELECT *
    FROM events SAMPLE 0.1
    WHERE team_id IN (SELECT team_id FROM teams_with_ai_events)
      AND event IN ({event_types_sql})
      AND toDate(timestamp) = '{metric_date}'
),
teams_with_llma_pageviews AS (
    SELECT DISTINCT team_id
    FROM events SAMPLE 0.1
    WHERE event = '$pageview'
      AND toDate(timestamp) = '{metric_date}'
      AND ({url_patterns_sql})
),
llma_pageview_events AS (
    SELECT *
    FROM events SAMPLE 0.1
    WHERE team_id IN (SELECT team_id FROM teams_with_llma_pageviews)
      AND event = '$pageview'
      AND toDate(timestamp) = '{metric_date}'
      AND ({url_patterns_sql})
)"""


def get_insert_query(metric_date: str) -> str:
    """
    Generate SQL to aggregate AI event counts by team and metric type for a single day.

    Uses long format: each metric_name is a separate row for easy schema evolution.
    Automatically discovers and combines all SQL templates in the sql/ directory.

    Args:
        metric_date: The date to aggregate metrics for (YYYY-MM-DD format)

    To add a new metric type, simply add a new .sql file in products/llm_analytics/dags/daily_metrics/sql/.
    Each SQL file should return columns: date, team_id, metric_name, metric_value
    """
    # Discover all SQL template files
    sql_files = sorted(SQL_DIR.glob("*.sql"))

    # Filter by enabled metrics if specified
    if ENABLED_METRICS is not None:
        sql_files = [f for f in sql_files if f.stem in ENABLED_METRICS]

    if not sql_files:
        raise ValueError(f"No SQL template files found in {SQL_DIR}")

    # Load and render each template
    rendered_queries = []
    template_context = {
        "event_types": config.ai_event_types,
        "pageview_mappings": config.pageview_mappings,
        "metric_date": metric_date,
        "include_error_rates": config.include_error_rates,
    }

    for sql_file in sql_files:
        with open(sql_file) as f:
            template = Template(f.read())
            rendered = template.render(**template_context)
            if rendered.strip():  # Only include non-empty queries
                rendered_queries.append(rendered)

    # Combine all queries with UNION ALL
    combined_query = "\n\nUNION ALL\n\n".join(rendered_queries)

    # Generate the llma_events CTE
    llma_events_cte = get_llma_events_cte(metric_date)

    # Wrap in INSERT INTO statement with CTE
    return f"""INSERT INTO {config.table_name} (date, team_id, metric_name, metric_value)

WITH {llma_events_cte}

{combined_query}"""


def get_delete_query(metric_date: str) -> str:
    """Generate SQL to delete existing data for the given date."""
    return f"ALTER TABLE {config.table_name} DELETE WHERE date = '{metric_date}'"
