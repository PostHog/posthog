from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.team import Team

# Kept free of intra-product imports so both `marketing_analytics_config` and
# `marketing_lazy_precompute` can use it without an import cycle.


def team_flag_target(team: "Team") -> tuple[str, dict[str, str | int], dict[str, dict[str, Any]]]:
    """`(distinct_id, groups, group_properties)` for a team-scoped marketing analytics rollout flag.

    Conditions on these flags must be organization or project *group* conditions: the distinct
    id is a team uuid with no person behind it, so a person or cohort condition is unresolvable
    and the flag keeps whatever the release conditions say for everyone. Turning such a flag off
    for a single user therefore has no effect on the query path at all.

    The project group is what makes a single-project opt-out possible — with only the
    organization group, the narrowest kill switch is the whole org.
    """
    return (
        str(team.uuid),
        {
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        {
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
    )
