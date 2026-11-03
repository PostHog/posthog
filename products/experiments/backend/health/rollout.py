import posthoganalytics

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils import flag_identity

# pinned: FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS in the frontend, which shows the findings.
HEALTH_FINDINGS_FLAG = "experiment-health-findings"


def runs_for_impersonated_session() -> bool:
    """
    Whether a staff member started this run in an impersonated session. A query runner has no session, so this reads
    the tag of the request, which follows an async run into the worker. The tag reads only the session cookie, so an
    OAuth token that was minted during impersonation is not an impersonated session here.
    """
    return bool(get_query_tags().is_impersonated)


def shows_health_findings(user: User, team: Team) -> bool:
    """
    Whether the web app shows the health findings to the user in the team. An impersonated session always shows them,
    because the user here is the customer, whom the flag can leave out. Otherwise it evaluates the app's flag locally,
    from the person and group inputs that the app sends to /flags, so it never waits on the network. An evaluation
    that is undecided or fails is False.
    """
    if runs_for_impersonated_session():
        return True
    identity = flag_identity(user, team, team.organization)
    if identity is None:
        return False
    try:
        enabled = posthoganalytics.feature_enabled(
            HEALTH_FINDINGS_FLAG,
            identity.distinct_id,
            groups=identity.groups,
            person_properties=identity.person_properties,
            group_properties=identity.group_properties,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        return False
    return bool(enabled)
