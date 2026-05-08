from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from posthog.models.utils import UUIDModel


class LensType(models.TextChoices):
    MONITOR = "monitor", "Monitor"
    CLASSIFIER = "classifier", "Classifier"
    SCORER = "scorer", "Scorer"
    SUMMARIZER = "summarizer", "Summarizer"
    INDEXER = "indexer", "Indexer"


class LensStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ERROR = "error", "Error"


class LensProvider(models.TextChoices):
    GOOGLE = "google", "Google"


class LensModel(models.TextChoices):
    GEMINI_3_FLASH = "gemini-3-flash", "Gemini 3 Flash"
    GEMINI_3_FLASH_LITE = "gemini-3-flash-lite", "Gemini 3 Flash Lite"


class ReplayLens(UUIDModel):
    """A configured probe that gets applied to completed session recordings (see README)."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=255, help_text="Human-readable name. Unique within the team.")
    description = models.TextField(
        blank=True,
        default="",
        help_text="Free-form description for the lens management UI. Not used by the model.",
    )

    lens_type = models.CharField(max_length=32, choices=LensType.choices)
    lens_config = models.JSONField(default=dict, help_text="Type-specific configuration; always includes `prompt`.")
    query = models.JSONField(
        default=dict,
        help_text="Persisted `posthog.schema.RecordingsQuery` shape; date_from/date_to stripped on save.",
    )
    sampling_rate = models.FloatField(
        default=1.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="0..1 random downsample applied after the query matches.",
    )

    provider = models.CharField(max_length=32, choices=LensProvider.choices, default=LensProvider.GOOGLE)
    model = models.CharField(max_length=64, choices=LensModel.choices)

    status = models.CharField(
        max_length=16,
        choices=LensStatus.choices,
        default=LensStatus.ACTIVE,
        help_text="Lifecycle state. Only `active` lenses are scheduled; `paused` and `error` lenses have their schedules removed by the reconciler.",
    )
    status_reason = models.TextField(blank=True, default="")

    is_builtin = models.BooleanField(default=False)
    emits_signals = models.BooleanField(default=False)

    lens_version = models.PositiveIntegerField(
        default=1,
        help_text="Increments on every config-changing save. Observations snapshot the version that produced them.",
    )
    last_swept_at = models.DateTimeField(
        default=timezone.now,
        help_text="Watermark for the lens schedule's last fire; mirrors Temporal schedule state for recovery.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="replay_lens_unique_team_name"),
            models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=0.0) & models.Q(sampling_rate__lte=1.0),
                name="replay_lens_sampling_rate_range",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status"], name="rl_team_status_idx"),
        ]

    # Fields that bump `lens_version` when changed — only those affecting what the lens does.
    _VERSION_TRACKED_FIELDS = (
        "lens_type",
        "lens_config",
        "query",
        "sampling_rate",
        "provider",
        "model",
        "emits_signals",
    )

    def save(self, *args, **kwargs) -> None:
        # Bump lens_version when any tracked field actually changed; SELECT FOR UPDATE
        # inside transaction.atomic() so concurrent saves can't both bump from the same baseline.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            relevant = [f for f in self._VERSION_TRACKED_FIELDS if f in update_fields]
        else:
            relevant = list(self._VERSION_TRACKED_FIELDS)
        if self.pk and relevant:
            with transaction.atomic():
                old = type(self).objects.select_for_update().filter(pk=self.pk).only("lens_version", *relevant).first()
                if old is not None and any(getattr(old, f) != getattr(self, f) for f in relevant):
                    self.lens_version = old.lens_version + 1
                    if update_fields is not None:
                        kwargs["update_fields"] = [*update_fields, "lens_version"]
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.lens_type})"
