"""A deployment row is only the request to deploy a SHA to an environment. Its outcome is in the
status rows, one per transition, so a deployment with no status rows has no outcome.
"""


def build_deployments_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            ifNull(sha, '') AS sha,
            ifNull(ref, '') AS ref,
            ifNull(environment, '') AS environment,
            coalesce(production_environment, false) AS is_production_environment,
            coalesce(transient_environment, false) AS is_transient_environment,
            parseDateTimeBestEffort(created_at) AS created_at,
            parseDateTimeBestEffort(updated_at) AS updated_at
        FROM {table_name}
    """


def build_deployment_statuses_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            deployment_id,
            ifNull(state, '') AS state,
            ifNull(environment, '') AS environment,
            parseDateTimeBestEffort(created_at) AS created_at
        FROM {table_name}
    """
