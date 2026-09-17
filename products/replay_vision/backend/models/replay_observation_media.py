from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ReplayObservationMedia(TeamScopedRootMixin, UUIDModel):
    """A thumbnail or clip for one observation. The bytes live on the `ExportedAsset`, which also carries
    the render state: no `content_location` means the render is still running, and `exception` means it
    failed. This row carries what an export asset has no place for: which observation owns the media,
    its order, the model's sentence, and the two time bases."""

    class Kind(models.TextChoices):
        THUMBNAIL = "thumbnail", "Thumbnail"
        CLIP = "clip", "Clip"

    observation = models.ForeignKey("replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="media")
    # CASCADE so the expiry sweep's asset delete takes this row with it, leaving no link to a gone object.
    asset = models.ForeignKey("exports.ExportedAsset", on_delete=models.CASCADE, related_name="+")
    # db_constraint=False: the migration policy blocks real FK constraints to the hot posthog_team table.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    kind = models.CharField(max_length=16, choices=Kind.choices)
    position = models.PositiveSmallIntegerField(default=0)
    description = models.TextField(null=True, blank=True)

    # Analysis-video time, for seeking the player the person is looking at.
    video_start_ms = models.PositiveIntegerField()
    video_end_ms = models.PositiveIntegerField(null=True, blank=True)
    # Recording time, which is what the rasterizer was asked to render.
    rec_start_ms = models.PositiveIntegerField(null=True, blank=True)
    rec_end_ms = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Its unique index also serves the ordered read of one observation's media.
            models.UniqueConstraint(
                fields=["observation", "kind", "position"], name="unique_replay_observation_media_slot"
            ),
        ]
