"""Curated deployments and deployment-statuses query builders.

Maps the raw GitHub deploy snapshots (the ``deployments`` webhook feed and its
``deployment_statuses`` fan-out) into query-able columns. A deployment row is the
*request* to deploy a SHA to an environment; its outcome lives entirely in the
status rows (one per transition: pending → in_progress → success/failure/error,
plus the ``inactive`` a later deploy or rollback marks it with). The DORA reads
therefore always join the two — a deployment with no status rows has no outcome.

Same source discipline as every builder here: table names are resolved per team
(``logic.sources``), timestamps land as strings and parse via
``parseDateTimeBestEffort``, Nullable columns are ``ifNull``-guarded before use
(see ``source_schema``).
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
