"""Curated view over a repo's GitHub deployments, joined to the status that made them live.

A deployment row records only the *request* to deploy a ref; the moment the change is actually
serving is the first ``success`` status GitHub attaches to it. This builder collapses the pair into
one row per deployment so consumers read a single "went live at" timestamp, and drops deployments
that never succeeded — a deploy that failed or is still running never shipped anything.

``is_production`` answers "does this environment serve users" from GitHub's own
``production_environment`` flag, falling back to the environment's name. The flag is optional in
the deployment API and many repos never set it, so a name test is the only thing left; consumers
surface the environments they counted so a mis-classified name is visible rather than silent.
"""

SUCCESS_STATE = "success"

# `prod`, `production`, and the regional/suffixed forms (`prod-us`, `production_eu`). Deliberately
# anchored: `preview-pr-123` and `reproduction` must not read as production.
_PRODUCTION_NAME_PATTERN = "^prod(uction)?([-_.].*)?$"


def build_query(*, deployments_table: str, statuses_table: str) -> str:
    """Curated SELECT over a repo's deployments: one row per deployment that reached ``success``,
    carrying the request time, the go-live time, and whether the environment serves users."""
    return f"""
        SELECT environment, is_production, created_at, succeeded_at
        FROM (
            SELECT
                d.environment AS environment,
                (d.production_environment
                    OR match(lower(d.environment), '{_PRODUCTION_NAME_PATTERN}')) AS is_production,
                parseDateTimeBestEffort(d.created_at) AS created_at,
                minIf(parseDateTimeBestEffort(s.created_at), s.state = '{SUCCESS_STATE}') AS succeeded_at
            FROM {deployments_table} AS d
            LEFT JOIN {statuses_table} AS s ON s.deployment_id = d.id
            GROUP BY d.id, d.environment, d.production_environment, d.created_at
        )
        WHERE created_at IS NOT NULL AND succeeded_at IS NOT NULL
    """
