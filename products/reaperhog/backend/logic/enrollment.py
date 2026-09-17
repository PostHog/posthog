import logging
from collections.abc import Callable, Mapping

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.reaperhog.backend.logic.artefacts import EvidenceValue
from products.reaperhog.backend.logic.constants import FLAG_ENROLLMENT_LOOKBACK_DAYS, FLAG_ENROLLMENT_MIN_USERS

logger = logging.getLogger(__name__)


@frozen
class FlagEnrollment:
    evaluations: int
    users: int
    enabled_evaluations: int
    enabled_users: int


NO_ENROLLMENT = FlagEnrollment(evaluations=0, users=0, enabled_evaluations=0, enabled_users=0)

EnrollmentCounts = Mapping[str, FlagEnrollment]
EnrollmentLoader = Callable[[int], EnrollmentCounts]

_ENABLED = "coalesce(toString(properties.$feature_flag_response), '') NOT IN ('false', '')"


def enrollment_evidence(enrollment: FlagEnrollment | None) -> dict[str, EvidenceValue]:
    counts = enrollment or NO_ENROLLMENT
    return {
        "enrollment_lookback_days": FLAG_ENROLLMENT_LOOKBACK_DAYS,
        "evaluations": counts.evaluations,
        "users": counts.users,
        "enabled_evaluations": counts.enabled_evaluations,
        "enabled_users": counts.enabled_users,
        "sample_threshold_met": counts.users >= FLAG_ENROLLMENT_MIN_USERS,
        "enabled_seen": counts.enabled_evaluations > 0,
    }


def load_flag_enrollment(team_id: int) -> EnrollmentCounts:
    """Enrollment counts per flag, or nothing at all when the query cannot answer.

    A partial answer is worse than no answer here: an aggregate truncated by a timeout reads as
    "nobody was enabled", which is exactly the evidence that sends a live flag to deletion.
    """
    try:
        return _query_flag_enrollment(team_id)
    except Exception:
        logger.exception("ReaperHog: flag enrollment query failed; continuing without enrollment evidence")
        return {}


def _query_flag_enrollment(team_id: int) -> EnrollmentCounts:
    team = Team.objects.get(id=team_id)
    response = execute_hogql_query(
        query=(
            "SELECT properties.$feature_flag AS flag_key, count() AS evaluations, uniq(distinct_id) AS users, "
            f"countIf({_ENABLED}) AS enabled_evaluations, uniqIf(distinct_id, {_ENABLED}) AS enabled_users "
            "FROM events "
            f"WHERE event = '$feature_flag_called' AND timestamp > now() - INTERVAL {FLAG_ENROLLMENT_LOOKBACK_DAYS} DAY "
            "GROUP BY flag_key LIMIT 100000"
        ),
        team=team,
        query_type="reaperhog_flag_enrollment",
        workload=Workload.OFFLINE,
        settings=HogQLGlobalSettings(timeout_overflow_mode="throw"),
    )
    return {
        str(row[0]): FlagEnrollment(
            evaluations=int(row[1]), users=int(row[2]), enabled_evaluations=int(row[3]), enabled_users=int(row[4])
        )
        for row in response.results or []
        if row[0]
    }
