import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import IntegerField, Max, Value
from django.db.models.functions import Coalesce

from posthog.models.team.extensions import register_team_extension_signal

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = logging.getLogger(__name__)

# Ceiling on a staff-granted max_feature_flags_override. The global default exists to bound the
# flag-definitions blob and the flags service's in-memory flag set, so an unbounded grant would
# reintroduce the memory risk the limit was added for. This assumes MAX_FEATURE_FLAGS_PER_TEAM
# stays below it: raising that env var past this value would leave staff able only to lower a
# team's limit. A constant rather than a setting because it feeds the mutation serializer's
# max_value, which drf-spectacular bakes into api.zod.ts as a literal, and the CHECK constraint
# below, which a migration has to name at a fixed value.
# Lives here rather than in flag_limits.py so the model can bound its own field: flag_limits
# imports this module, so the constant has to sit on the lower side of that edge.
MAX_FEATURE_FLAGS_OVERRIDE_CEILING = 20_000


class PropertyMatchingVersion(models.IntegerChoices):
    LEGACY = 1, "Legacy"
    EXPLICIT = 2, "Explicit"


class FlagEvaluationsMode(models.IntegerChoices):
    """Which table the product reads a team's $feature_flag_called data from. This field does not
    control ingestion. The INGESTION_FLAG_EVALUATIONS_TEAMS allowlist in FlagEvaluationsService
    decides which teams ingestion also writes to flag_evaluations. FLAG_EVALUATIONS_ONLY is
    reserved for the ingestion change that stops the events writes.
    """

    # The Usage tab reads the events table. The flag_evaluations HogQL table stays hidden unless
    # the flag-evaluations-hogql-table flag is on for the organization.
    EVENTS = 0, "Events"
    # The Usage tab reads flag_evaluations, and the HogQL table is visible.
    READ_FLAG_EVALUATIONS = 1, "Read flag evaluations"
    # As READ_FLAG_EVALUATIONS, and ingestion stops writing $feature_flag_called to events. Ingestion
    # ignores this mode until the change that implements it deploys. Until then the mode acts as
    # READ_FLAG_EVALUATIONS. A team already on this mode stops the events writes when that change deploys.
    FLAG_EVALUATIONS_ONLY = 2, "Flag evaluations only"


def flag_evaluations_mode_annotation() -> Coalesce:
    """Each team's mode, for a Team queryset. A team without a config row reads EVENTS, as every reader does."""
    return Coalesce(
        "teamfeatureflagsconfig__flag_evaluations_mode",
        Value(FlagEvaluationsMode.EVENTS),
        output_field=IntegerField(),
    )


class TeamFeatureFlagsConfig(models.Model):
    """Internal-only team-level feature flags settings, written by staff and never by customers.

    Never let a customer-facing serializer, API endpoint, or settings UI write this model.
    It holds server-controlled behavior rollouts and staff-granted limit overrides, not
    customer-editable preferences. The one customer-facing read is flag_evaluations_mode, which
    the team serializer exposes read-only because the frontend picks the Usage tab source from it.
    The staff-only feature-flags-staff API
    (products/feature_flags/backend/api/staff_team_config.py, gated by IsStaffUser) is the only
    interactive write surface: it changes SDK-facing behavior one team at a time after staff
    verify compatible SDK versions, and it grants per-team flag-count overrides.
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

    # Version 1 preserves released SDK behavior. Version 2 uses explicit scalar and array
    # equality semantics. The database default protects older writers during rolling deploys.
    property_matching_version = models.SmallIntegerField(
        choices=PropertyMatchingVersion,
        default=PropertyMatchingVersion.LEGACY,
        db_default=PropertyMatchingVersion.LEGACY,
    )

    # Raises or lowers this team's flag-count cap. Null means no override, falling back to the
    # global settings.MAX_FEATURE_FLAGS_PER_TEAM. Resolved by
    # products/feature_flags/backend/flag_limits.py, and read only when a flag is created.
    # The validators only fire under full_clean() (a Django admin ModelForm), which no writer
    # uses today; the CHECK constraint below is what actually holds the bounds on every path,
    # including a management command that writes the field directly.
    max_feature_flags_override = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_FEATURE_FLAGS_OVERRIDE_CEILING)],
    )

    # Set by default_values_for_team when the team is created, and changed after that only by staff
    # or a management command. A later change to FLAG_EVALUATIONS_NEW_ORG_MODE does not move
    # an existing team. Node ingestion reads this column straight from Postgres, so the database
    # default keeps its raw query and older writers valid during rolling deploys.
    flag_evaluations_mode = models.SmallIntegerField(
        choices=FlagEvaluationsMode,
        default=FlagEvaluationsMode.EVENTS,
        db_default=FlagEvaluationsMode.EVENTS,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="max_feature_flags_override_in_range",
                condition=models.Q(max_feature_flags_override__isnull=True)
                | models.Q(
                    max_feature_flags_override__gte=1,
                    max_feature_flags_override__lte=MAX_FEATURE_FLAGS_OVERRIDE_CEILING,
                ),
            )
        ]

    @classmethod
    def default_values_for_team(cls, team: "Team") -> dict[str, Any]:
        """Per-team values for the row the team-creation signal creates. get_or_create_team_extension
        does not apply them, because a row it creates later must keep the EVENTS mode that every
        reader already reported for the missing row.

        A team copies the mode of a sibling team in its organization, so an organization stays on
        one mode and a new project inherits the mode of the organization. A sibling without a
        config row counts as EVENTS, because every reader treats a missing row that way. Only the
        first team of an organization takes FLAG_EVALUATIONS_NEW_ORG_MODE.
        """
        # The query starts from Team so that a sibling without a config row still counts. type(team)
        # gives the Team model without an import in this module. The highest mode wins when siblings
        # disagree, because a new team has no history in the events table that a higher mode could hide.
        sibling_mode = (
            type(team)
            .objects.filter(organization_id=team.organization_id)
            .exclude(id=team.id)
            .aggregate(mode=Max(flag_evaluations_mode_annotation()))["mode"]
        )
        if sibling_mode is not None:
            return {"flag_evaluations_mode": sibling_mode}

        new_org_mode = settings.FLAG_EVALUATIONS_NEW_ORG_MODE
        if new_org_mode not in FlagEvaluationsMode.values:
            # No database constraint holds the column to the choices, and the readers disagree on
            # an unknown value, so an out-of-range setting falls back to the events table.
            logger.warning("Ignoring invalid FLAG_EVALUATIONS_NEW_ORG_MODE %r", new_org_mode)
            new_org_mode = FlagEvaluationsMode.EVENTS
        return {"flag_evaluations_mode": new_org_mode}


register_team_extension_signal(TeamFeatureFlagsConfig, logger=logger)
