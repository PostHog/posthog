from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal, TypeVar, cast

import structlog

from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import ErrorTrackingIssue

from .base import Recommendation

logger = structlog.get_logger(__name__)

# Shared with FEATURE_FLAGS.ERROR_TRACKING_IMPACT in frontend/src/lib/constants.tsx, which gates the impact tab.
# The backend evaluates it locally against the project and organization groups only, see impact_enabled.
IMPACT_FEATURE_FLAG = "error-tracking-impact"

WINDOW_HOURS = 24
MAX_ISSUES = 20

# Resolves each exception to its current issue through the fingerprint state, so merged and deleted issues are
# handled. The event's own $exception_issue_id goes stale when issues merge.
ISSUE_STATE_JOIN = """
    {kind} JOIN (
        SELECT
            team_id,
            fp_hash,
            tupleElement(state, 1) AS issue_id,
            tupleElement(state, 2) AS issue_status
        FROM (
            SELECT
                team_id,
                cityHash64(fingerprint) AS fp_hash,
                argMax((issue_id, issue_status), version) AS state
            FROM error_tracking_fingerprint_issue_state
            WHERE team_id IN %(team_ids)s
            GROUP BY team_id, fp_hash
            HAVING argMax(is_deleted, version) = 0
            SETTINGS optimize_aggregation_in_order=1
        )
    ) AS issue_state
        ON events.team_id = issue_state.team_id
        AND cityHash64({fingerprint}) = issue_state.fp_hash
"""


# Host plus path, with ids replaced by placeholders, so /orders/123 and /orders/456 count as one page.
PAGE_PATH = """concat(
    {host},
    replaceRegexpAll(
        replaceRegexpAll(
            replaceRegexpAll({pathname}, '[0-9a-fA-F]{{8}}-[0-9a-fA-F-]{{20,}}', ':uuid'),
            '/[0-9]+', '/:n'
        ),
        '/[A-Za-z0-9_-]{{16,}}', '/:id'
    )
)"""


def property_expr(property_name: str) -> str:
    column = get_materialized_column_for_property("events", "properties", property_name)
    if column is None:
        # JSONExtractRaw keeps numeric values such as $browser_version, which JSONExtractString drops.
        return f"replaceRegexpAll(JSONExtractRaw(events.properties, '{property_name}'), '^\"|\"$', '')"
    if column.is_nullable:
        return f"ifNull(events.`{column.name}`, '')"
    return f"events.`{column.name}`"


def page_path_expr() -> str:
    return PAGE_PATH.format(host=property_expr("$host"), pathname=property_expr("$pathname"))


def issue_state_join(kind: Literal["INNER", "LEFT"] = "INNER") -> str:
    return ISSUE_STATE_JOIN.format(kind=kind, fingerprint=property_expr("$exception_fingerprint"))


def issue_summaries(team_ids: list[int], issue_ids: list[str]) -> dict[tuple[int, str], dict[str, Any]]:
    """The name, description and status of each issue that still exists in Postgres, by team and issue id.

    Keying by team as well keeps a team's result free of another team's issue, even if a query joined across teams.
    """
    return {
        (issue.team_id, str(issue.id)): {
            "id": str(issue.id),
            "name": issue.name or "Untitled issue",
            "description": issue.description,
            "status": issue.status,
        }
        # nosemgrep: idor-lookup-without-team (team_id__in scopes the lookup; background compute, not user input)
        for issue in ErrorTrackingIssue.objects.filter(team_id__in=team_ids, id__in=issue_ids).only(
            "id", "team_id", "name", "description", "status"
        )
    }


def with_issue_details(
    team_ids: list[int], issues_by_team: dict[int, list[dict[str, Any]]]
) -> dict[int, list[dict[str, Any]]]:
    """Adds the name, description and status of each issue, and drops issues that no longer exist in Postgres."""
    summaries = issue_summaries(team_ids, [issue["id"] for issues in issues_by_team.values() for issue in issues])
    result: dict[int, list[dict[str, Any]]] = {team_id: [] for team_id in team_ids}
    for team_id, issues in issues_by_team.items():
        for issue in issues:
            summary = summaries.get((team_id, issue["id"]))
            if summary is not None:
                result[team_id].append({**issue, **summary})
    return result


def impact_enabled(team: Team) -> bool:
    """Whether the impact lenses run for a team.

    The flag is evaluated locally, with only the team's project and organization as groups. Target it by
    organization or project: a condition on any other property, such as a person's email or a cohort, cannot
    evaluate here and reads false, so the lenses never compute even when the tab shows for that person.
    """
    # A flag-evaluation failure hides the feature rather than computing it for every team: fail closed.
    try:
        return feature_enabled_or_false(
            IMPACT_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id), "uuid": str(team.uuid)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("error_tracking_impact_flag_check_failed", team_id=team.id, exc_info=True)
        return False


T = TypeVar("T")

_batch_results: ContextVar[dict[tuple[Hashable, ...], dict[int, Any]] | None] = ContextVar(
    "error_tracking_impact_batch_results", default=None
)


@contextmanager
def shared_batch_results() -> Iterator[None]:
    """Lets the lenses of one sweep batch reuse each other's per-team query results, so a query that two lenses
    need runs once per team. Outside this context every lens queries on its own."""
    token = _batch_results.set({})
    try:
        yield
    finally:
        _batch_results.reset(token)


def per_team_results(
    key: tuple[Hashable, ...], team_ids: list[int], fetch: Callable[[list[int]], dict[int, T]], empty: Callable[[], T]
) -> dict[int, T]:
    """The per-team result of ``fetch`` for every team, fetching only the teams this batch has not fetched yet.

    ``key`` names the query and its inputs other than the teams, such as its time window.
    """
    cache = _batch_results.get()
    known: dict[int, Any] = {} if cache is None else cache.setdefault(key, {})
    missing = [team_id for team_id in team_ids if team_id not in known]
    if missing:
        fetched = fetch(missing)
        for team_id in missing:
            known[team_id] = fetched.get(team_id, empty())
    return {team_id: cast(T, known[team_id]) for team_id in team_ids}


class ImpactLens(Recommendation):
    """A recommendation that the impact tab shows as a lens. It lists issues and runs only for teams in the impact flag."""

    # Lenses scan pageviews over days, so the sweep computes them for a few teams at a time and heartbeats between.
    max_teams_per_compute = 10

    def is_enabled_for_team(self, team: Team) -> bool:
        return impact_enabled(team)

    def is_completed(self, meta: dict[str, Any]) -> bool:
        # A lens is information, not a task: an empty list means nothing was flagged, not that work is done.
        return False
