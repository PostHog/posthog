"""Row-level fingerprinted CI failure lines from the Logs product — the failure-index substrate.

The CI job-logs worker emits one Logs record per failure line (service ``github-ci-logs``, see
``job_logs``). This view keeps only the pytest ``FAILED <nodeid>`` lines and turns each into a
fingerprinted row so a caller can count "how often is this exact failure happening, and on which
branches / SHAs / PRs" without re-deriving the fingerprint recipe every time.

One row per pytest FAILED line. ``test_id`` is the node id from ``FAILED <id>``; ``error_signature``
is the trailing ``" - <detail>"`` with volatile bits normalized to ``N`` (long hex/uuid blobs and
digit runs) so two runs of the same failure share a signature; ``fingerprint`` is
``test_id | signature`` — the group key. The run/branch/repo/job attributes ride the emitted log
record, and ``run_id`` / ``job_id`` are cast to Int so they join against ``ci_job_history`` and the
raw ``github_*`` tables.

The fingerprint recipe is **pytest-only v1** — jest / playwright / cargo failure lines don't match
``FAILED <id>`` and are not fingerprinted yet. The recipe lives in code (not a stored materialization)
on purpose, so it can evolve by PR as more test runners are covered, re-rendering into a team's view
on the next sync.

Reads the ``logs`` table, not the warehouse — the failure lines live in the Logs product. Team-global
(logs aren't source-scoped), so there is no per-source resolution; the view is still gated on the team
having a qualifying GitHub source so it appears alongside ``ci_job_history``. Nothing here is
registered as a global HogQL view; it is provisioned per-team as a non-materialized
``DataWarehouseSavedQuery`` by data_modeling's managed-viewset sync.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, IntegerDatabaseField, StringDatabaseField

from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.sources import resolve_job_cost_source_pairs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Public view name — stable contract for insights, subscriptions, other products, and execute-sql.
VIEW_NAME = "engineering_analytics_ci_failures"

# Public column contract (order fixes the saved-query schema). ``nullable=True`` where a value can be
# absent: no trailing detail → NULL signature; an unstamped conclusion attribute → NULL conclusion.
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
}

# ``__SERVICE_NAME__`` is substituted with the constant below (a plain identifier, not user input) —
# .replace, not an f-string, so the ``{8,}`` regex quantifier doesn't collide with f-string braces.
# The inner layer extracts test_id + the normalized signature; the outer layer derives error_signature
# (NULL when empty) and the fingerprint off those projected columns (a same-SELECT alias can't feed
# another expression). Volatile bits — long hex/uuid runs and digit runs — collapse to ``N`` so the
# same failure across runs shares a signature, truncated to keep the group key bounded.
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
        conclusion
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
            nullIf(attributes['conclusion'], '') AS conclusion
        FROM logs
        WHERE service_name = '__SERVICE_NAME__' AND regexpExtract(body, 'FAILED ([^[:space:]]+::[^[:space:]]+)') != ''
    )
"""


def build_query() -> str:
    """The failure-line SELECT over the team's Logs. No per-source table — logs are team-global."""
    return _SELECT.replace("__SERVICE_NAME__", CI_LOGS_SERVICE_NAME)


def build_team_view(team: "Team") -> str | None:
    """The view body, or None when the team has no qualifying GitHub source.

    Gated on the same ``resolve_job_cost_source_pairs`` condition as ``ci_job_history`` so the two
    views always appear together — a team without a synced GitHub jobs/runs source gets neither.
    """
    if not resolve_job_cost_source_pairs(team):
        return None
    return build_query()
