import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

# Per-user gate for surfacing `signals_scout`-sourced reports in the inbox. The scout is a
# new signal source; this flag is the final, narrow rollout step that lets its reports appear
# in the inbox (which already shows other sources) — and lets us hold them back for internal
# sense-checking first. It layers above the `signals-scout` run flag: a team can be running
# and emitting scouts while their reports stay hidden from users until this flips on.
SIGNALS_SCOUT_INBOX_FLAG = "signals-scout-inbox"


def user_can_see_signals_scout_reports(user: User, team: Team) -> bool:
    """Whether `signals_scout`-sourced reports should surface in the inbox for this user.

    Evaluated remotely: the flag's release conditions are person-level (an internal-user
    allowlist for dogfooding), which local eval can't decide without the person properties —
    remote eval sidesteps that, matching `products/tasks/backend/access.py`. Organization +
    project group context is passed so the flag can also be targeted per project. Fails closed:
    any eval failure (or a user without a `distinct_id`) hides scout reports rather than
    leaking them before rollout.
    """
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False
    org_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SIGNALS_SCOUT_INBOX_FLAG,
                distinct_id,
                groups={"organization": org_id, "project": str(team.id)},
                group_properties={
                    "organization": {"id": org_id},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        capture_exception(error)
        return False
