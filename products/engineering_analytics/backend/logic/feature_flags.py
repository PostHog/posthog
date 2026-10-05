"""How this product evaluates a feature flag for a team."""

import posthoganalytics

from posthog.models.team import Team


def team_flag(
    key: str, team: Team, *, distinct_id: str | None = None, only_evaluate_locally: bool = False
) -> bool | None:
    """The flag's value for the team, or None when the flag service gives no answer.

    The team's organization and project are passed as groups, so a flag can be released to either.
    ``distinct_id`` is the person to evaluate as. Without one the team stands in, which matches only
    a release to a group. ``only_evaluate_locally`` is for a request path: the evaluation then never
    waits on the network, and a flag the local definitions cannot decide gives None.
    """
    org_id = str(team.organization_id)
    project_id = str(team.id)
    return posthoganalytics.feature_enabled(
        key,
        distinct_id or str(team.uuid),
        groups={"organization": org_id, "project": project_id},
        group_properties={"organization": {"id": org_id}, "project": {"id": project_id}},
        only_evaluate_locally=only_evaluate_locally,
        send_feature_flag_events=False,
    )
