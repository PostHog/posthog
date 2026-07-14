import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamFeatureFlagsConfig(models.Model):
    """Internal-only team-level feature flags behavior settings.

    Never expose this model through a customer-facing serializer, API endpoint, or settings UI.
    It gates server-controlled behavior rollouts, not customer preferences. The one exception is
    the staff-only feature-flags-staff API (products/feature_flags/backend/api/staff_team_config.py,
    gated by IsStaffUser), which lets staff flip minimal_flag_called_events for one team at a time
    after manually verifying that team's SDK versions support the slim event shape.
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


register_team_extension_signal(TeamFeatureFlagsConfig, logger=logger)
