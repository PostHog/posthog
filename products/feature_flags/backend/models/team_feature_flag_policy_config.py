from django.contrib.postgres.fields import ArrayField
from django.db import models

from products.feature_flags.backend.facade.request_blocklist import MAX_BLOCKED_HOST_LENGTH, MAX_BLOCKED_IP_LENGTH


class TeamFeatureFlagPolicyConfig(models.Model):
    """Customer-editable feature flag rules for a team.

    Distinct from TeamFeatureFlagsConfig, which holds staff-only rollout switches and is never
    exposed to customers. This one is reachable by project admins as `feature_flag_policy_config`
    on the team/project API.

    The require_tags rule is bookkeeping, and it does not hold on every write path. The exemptions
    are declared by the caller, and a path that builds a serializer context without `get_team` skips
    the rule entirely: the organization-level flag copy and the approvals apply path both do.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    # related_name="+": the relation crosses a product boundary, so it must not add a reverse
    # accessor to Team. Readers come in through `Team.feature_flag_policy_config` instead.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    # Blocks creating a flag with no tags, and blocks removing the last tag from a flag that has
    # one. Only applies to flags a person creates directly. Flags generated to back a survey,
    # experiment, early access feature, product tour, or web experiment are exempt, because those
    # forms have no tag input and would otherwise dead-end.
    require_tags = models.BooleanField(default=False)

    # Saving does not normalize these lists, so every writer goes through facade.request_blocklist first.
    # db_default lets pods on the previous release insert rows without naming these columns.
    blocked_hosts = ArrayField(
        models.CharField(max_length=MAX_BLOCKED_HOST_LENGTH), default=list, blank=True, db_default=[]
    )
    blocked_ips = ArrayField(
        models.CharField(max_length=MAX_BLOCKED_IP_LENGTH), default=list, blank=True, db_default=[]
    )


def team_requires_flag_tags(team_id: int) -> bool:
    """Whether this team requires tags on flags.

    Queries the row rather than going through ``get_or_create_team_extension`` so a read on the
    flag-write path does not create the row for every team that never touched the setting.
    """
    return (
        TeamFeatureFlagPolicyConfig.objects.filter(team_id=team_id).values_list("require_tags", flat=True).first()
        is True
    )
