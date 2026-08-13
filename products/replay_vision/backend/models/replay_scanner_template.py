from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.replay_vision.backend.models.replay_scanner import (
    SamplingMode,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)


class ReplayScannerTemplate(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
    )
    source_scanner = models.ForeignKey(
        "replay_vision.ReplayScanner",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custom_templates",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    scanner_type = models.CharField(max_length=32, choices=ScannerType.choices)
    scanner_config = models.JSONField(default=dict)
    query = models.JSONField(default=dict)
    sampling_rate = models.FloatField(default=1.0)
    sampling_mode = models.CharField(
        max_length=20,
        choices=SamplingMode.choices,
        default=SamplingMode.COMPREHENSIVE,
    )
    provider = models.CharField(max_length=32, choices=ScannerProvider.choices, default=ScannerProvider.GOOGLE)
    model = models.CharField(max_length=64, choices=ScannerModel.choices)
    emits_signals = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_scanner"],
                name="replay_scanner_template_unique_source",
            ),
        ]

    def __str__(self) -> str:
        return self.name
