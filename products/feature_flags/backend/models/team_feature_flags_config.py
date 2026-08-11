import logging

from django.core.validators import MinValueValidator
from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamFeatureFlagsConfig(models.Model):
    """Internal-only team-level feature flags settings, written by staff and never by customers.

    Never expose this model through a customer-facing serializer, API endpoint, or settings UI.
    It holds server-controlled behavior rollouts and staff-granted limit overrides, not
    customer-editable preferences. The staff-only feature-flags-staff API
    (products/feature_flags/backend/api/staff_team_config.py, gated by IsStaffUser) is the only
    interactive write surface: it flips minimal_flag_called_events one team at a time after staff
    manually verify that team's SDK versions support the slim event shape, and it grants per-team
    flag-count overrides.
    Sanctioned writers: the team-creation signal below, get_or_create_team_extension, the
    staff-only feature-flags-staff API (gated by IsStaffUser), and management commands.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    # Allows SDKs to send slim $feature_flag_called events for flags without a
    # linked experiment. False = full events (legacy behavior). Stays False for
    # all teams, new or existing, until SDKs support the slim event shape; flip
    # per-team via the feature-flags-staff API once verified, or in bulk via a
    # management command.
    minimal_flag_called_events = models.BooleanField(default=False)

    # Raises or lowers this team's flag-count cap. Null means no override, falling back to the
    # global settings.MAX_FEATURE_FLAGS_PER_TEAM. Resolved by
    # products/feature_flags/backend/flag_limits.py, and read only when a flag is created.
    # MinValueValidator is defense in depth for management commands and Django admin, since the
    # staff API uses a plain Serializer that never calls full_clean(); its real bounds live there.
    max_feature_flags_override = models.PositiveIntegerField(
        null=True, blank=True, default=None, validators=[MinValueValidator(1)]
    )


register_team_extension_signal(TeamFeatureFlagsConfig, logger=logger)
