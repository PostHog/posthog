import logging

from django.db import models

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamExperimentsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    experiment_recalculation_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Time of day (UTC) when experiment metrics should be recalculated. If not set, uses the default recalculation time.",
    )

    default_experiment_confidence_level = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Default confidence level for new experiments in this environment. Valid values: 0.90, 0.95, 0.99.",
    )

    default_experiment_stats_method = models.CharField(
        max_length=20,
        choices=Organization.DefaultExperimentStatsMethod,
        default=Organization.DefaultExperimentStatsMethod.BAYESIAN,
        null=True,
        blank=True,
        help_text="Default statistical method for new experiments in this environment.",
    )

    experiment_precomputation_enabled = models.BooleanField(
        default=False,
        help_text="Whether to precompute experiment exposure data for faster query execution.",
    )

    default_only_count_matured_users = models.BooleanField(
        default=False,
        help_text="Default value for 'only count matured users' on new experiments in this environment.",
    )

    funnel_steps_data_disabled = models.BooleanField(
        default=False,
        help_text=(
            "Default for disabling per-step session/event sample data on funnel experiment metrics. "
            "Overridden by the experiment-level `funnel_steps_data_disabled` parameter when set."
        ),
    )


register_team_extension_signal(TeamExperimentsConfig, logger=logger)
