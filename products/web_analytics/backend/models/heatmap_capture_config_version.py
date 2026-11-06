from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.team_heatmap_config import TeamHeatmapConfig
from posthog.models.utils import UUIDModel


class HeatmapCaptureConfigVersion(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    mode = models.CharField(max_length=20, choices=TeamHeatmapConfig.CaptureMode.choices)
    patterns = ArrayField(models.CharField(max_length=2000), default=list, blank=True, db_default=[])
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    class Meta:
        db_table = "posthog_heatmapcaptureconfigversion"
        indexes = [
            models.Index(fields=["team", "effective_from", "effective_to"], name="heatmap_capture_ver_team_idx"),
        ]
