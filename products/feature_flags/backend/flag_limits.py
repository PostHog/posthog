from django.conf import settings

from posthog.models.team import Team

from products.feature_flags.backend.models.team_feature_flags_config import TeamFeatureFlagsConfig

# Ceiling on a staff-granted override. The global default exists to bound the flag-definitions
# blob and the flags service's in-memory flag set, so an unbounded grant would reintroduce the
# memory risk the limit was added for. This assumes MAX_FEATURE_FLAGS_PER_TEAM stays below it:
# raising that env var past this value would leave staff able only to lower a team's limit.
# A constant rather than a setting because it feeds the mutation serializer's max_value, which
# drf-spectacular bakes into api.zod.ts as a literal.
MAX_FEATURE_FLAGS_OVERRIDE_CEILING = 20_000


def resolve_max_feature_flags(override: int | None) -> int:
    """Effective flag-count cap for a team, given its stored override."""
    return override if override is not None else settings.MAX_FEATURE_FLAGS_PER_TEAM


def root_team_id_for(team_id: int) -> int:
    """Project root for a team id, or the id itself when it is already the root or unknown."""
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
        TeamFeatureFlagsConfig.objects.filter(team_id=root_team_id_for(team_id))
        .values_list("max_feature_flags_override", flat=True)
        .first()
    )


def get_max_feature_flags_for_team(team_id: int) -> int:
    """Effective flag-count cap for a team: its root-resolved override, or the global default."""
    return resolve_max_feature_flags(get_max_feature_flags_override_for_team(team_id))
