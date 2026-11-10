"""One row per pytest ``FAILED <nodeid>`` line that the CI job-logs pipeline emitted to Logs.

``fingerprint`` is ``test_id | error_signature`` and groups the same failure across runs. Only pytest
lines are fingerprinted, because other runners do not print ``FAILED <id>::<id>``.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, IntegerDatabaseField, StringDatabaseField

from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import resolve_job_source_tables

if TYPE_CHECKING:
    from posthog.models.team import Team

# Saved queries and insights select this view by name, so a rename breaks them.
VIEW_NAME = "engineering_analytics_ci_failures"

# The column order is the saved-query schema, so append new columns and never reorder.
FIELDS: dict[str, FieldOrTable] = {
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "test_id": StringDatabaseField(name="test_id"),
    "error_signature": StringDatabaseField(name="error_signature", nullable=True),
    "fingerprint": StringDatabaseField(name="fingerprint"),
    "branch": StringDatabaseField(name="branch"),
    "head_sha": StringDatabaseField(name="head_sha"),
    "repo": StringDatabaseField(name="repo"),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "job_name": StringDatabaseField(name="job_name"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "job_id": IntegerDatabaseField(name="job_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt", nullable=True),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "ci_engine": StringDatabaseField(name="ci_engine", nullable=True),
}

# ``__SERVICE_NAME__`` is filled in with ``str.replace``, because the ``{8,}`` regex quantifier would
# collide with f-string braces. Long hex runs and digit runs collapse to ``N`` so that the same
# failure shares one signature across runs.
_SELECT = """
    SELECT
        `timestamp`,
        test_id,
        nullIf(signature, '') AS error_signature,
        concat(test_id, ' | ', signature) AS fingerprint,
        branch,
        head_sha,
        repo,
        workflow_name,
        job_name,
        run_id,
        job_id,
        run_attempt,
        conclusion,
        ci_engine
    FROM (
        SELECT
            `timestamp`,
            -- The '::' requirement is what makes this pytest-specific: CI log lines containing FAILED
            -- in other contexts (env dumps, stage markers) carry no '::' node id and are dropped.
            -- Primary: non-greedy capture up to the FIRST ' - ' separator (pytest short-summary format),
            -- which keeps spaces inside parameterized ids like test_x[user 123]. Fallback: the no-space
            -- form, for FAILED lines without a ' - ' detail suffix. Residual limitation: a param value
            -- containing a literal ' - ' still truncates at it — regex can't disambiguate that from the
            -- message separator.
            coalesce(nullIf(regexpExtract(body, 'FAILED (.+?::.*?) - '), ''), regexpExtract(body, 'FAILED ([^[:space:]]+::[^[:space:]]+)')) AS test_id,
            substring(replaceRegexpAll(regexpExtract(body, ' - (.*)$'), '[0-9a-fA-F-]{8,}|[0-9]+', 'N'), 1, 200) AS signature,
            attributes['branch'] AS branch,
            attributes['head_sha'] AS head_sha,
            attributes['repo'] AS repo,
            attributes['workflow_name'] AS workflow_name,
            attributes['job_name'] AS job_name,
            accurateCastOrNull(attributes['run_id'], 'Int64') AS run_id,
            accurateCastOrNull(attributes['job_id'], 'Int64') AS job_id,
            accurateCastOrNull(attributes['run_attempt'], 'Int64') AS run_attempt,
            nullIf(attributes['conclusion'], '') AS conclusion,
            nullIf(attributes['ci_engine'], '') AS ci_engine
        FROM logs
        WHERE service_name = '__SERVICE_NAME__' AND regexpExtract(body, 'FAILED ([^[:space:]]+::[^[:space:]]+)') != ''
    )
"""


def build_query() -> str:
    """The view's SELECT. It takes no table name because Logs are not scoped to a GitHub source."""
    return _SELECT.replace("__SERVICE_NAME__", CI_LOGS_SERVICE_NAME)


def build_team_view(team: "Team") -> str | None:
    """The view body, or None when the team has no GitHub source with runs and jobs synced.

    The gate matches ``ci_job_history`` so that a team gets both views or neither.
    """
    if not resolve_job_source_tables(team):
        return None
    return build_query()
