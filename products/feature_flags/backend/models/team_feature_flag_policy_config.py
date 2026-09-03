import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamFeatureFlagPolicyConfig(models.Model):
    """Customer-editable rules that guard how a team's members create flags.

    Distinct from TeamFeatureFlagsConfig, which holds staff-only rollout switches and is never
    exposed to customers. This one is reachable by project admins as `feature_flag_policy_config`
    on the team/project API.

    These rules are bookkeeping, and they do not hold on every write path. The exemptions are
    declared by the caller, and a path that builds a serializer context without `get_team` skips
    the rules entirely: the organization-level flag copy and the approvals apply path both do.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    # Blocks creating a flag with no tags, and blocks removing the last tag from a flag that has
    # one. Only applies to flags a person creates directly. Flags generated to back a survey,
    # experiment, early access feature, product tour, or web experiment are exempt, because those
    # forms have no tag input and would otherwise dead-end.
    require_tags = models.BooleanField(default=False)


register_team_extension_signal(TeamFeatureFlagPolicyConfig, logger=logger)


def team_requires_flag_tags(team_id: int) -> bool:
    """Whether this team requires tags on flags.

    Queries the row rather than going through ``get_or_create_team_extension`` so a read on the
    flag-write path does not create the row for every team that never touched the setting.
    """
    return (
        TeamFeatureFlagPolicyConfig.objects.filter(team_id=team_id).values_list("require_tags", flat=True).first()
        is True
    )
