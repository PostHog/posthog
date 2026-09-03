from django.conf import settings

from posthog.models.team import Team

from products.feature_flags.backend.models.team_feature_flags_config import TeamFeatureFlagsConfig


def resolve_max_feature_flags(override: int | None) -> int:
    """Effective flag-count cap for a team, given its stored override."""
    return override if override is not None else settings.MAX_FEATURE_FLAGS_PER_TEAM


def _root_team_id_for(team_id: int) -> int:
    """Project root for a team id, or the id itself when it is already the root or unknown.

    Deliberately does not raise the way posthog.models.scoping.manager.resolve_effective_team_id
    does: an unknown team here should fall back to the global default rather than 500 a flag
    create. Private because that difference makes it wrong to reach for from outside this module.
    """
    return Team.objects.filter(id=team_id).values_list("parent_team_id", flat=True).first() or team_id


def get_max_feature_flags_override_for_team(team_id: int) -> int | None:
    # Resolved against the project root because the flag count this bounds is project-scoped:
    # RootTeamMixin.save stores every flag under the root team, and check_flag_limits_for_team
    # counts through FeatureFlag.objects, whose RootTeamManager rewrites team_id= to the root.
    # Callers also disagree on which id they pass (the viewset passes project_id, the facade
    # passes the request's own team), so reading the literal team would let a grant apply on one
    # path and not the other. The staff API's read side has the same requirement: displaying an
    # environment team's own row would show no override even when its project root has one.
    #
    # A missing config row and a row holding a null override both mean "no override", and
    # .first() returns None for both.
    return (
        TeamFeatureFlagsConfig.objects.filter(team_id=_root_team_id_for(team_id))
        .values_list("max_feature_flags_override", flat=True)
        .first()
    )


def get_max_feature_flags_for_team(team_id: int) -> int:
    """Effective flag-count cap for a team: its root-resolved override, or the global default."""
    return resolve_max_feature_flags(get_max_feature_flags_override_for_team(team_id))
