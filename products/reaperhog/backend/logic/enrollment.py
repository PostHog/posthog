from collections.abc import Callable, Mapping

from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.reaperhog.backend.logic.artefacts import EvidenceValue
from products.reaperhog.backend.logic.constants import FLAG_ENROLLMENT_LOOKBACK_DAYS


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
    }


def load_flag_enrollment(team_id: int) -> EnrollmentCounts:
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
    )
    return {
        str(row[0]): FlagEnrollment(
            evaluations=int(row[1]), users=int(row[2]), enabled_evaluations=int(row[3]), enabled_users=int(row[4])
        )
        for row in response.results or []
        if row[0]
    }
