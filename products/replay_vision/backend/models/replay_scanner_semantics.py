from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

# A theme waits for this many members before its first name, so a one-off session never costs a model call.
THEME_FIRST_RENAME_AT = 5


class ReplayScannerSemanticCenter(TeamScopedRootMixin, models.Model):
    """A scanner's running sum of issue observation vectors. Themes and feed groups compare vectors with this mean
    taken out, because every observation of one scanner shares its question's wording."""

    scanner = models.OneToOneField(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "replay_vision"


class ReplayScannerSearchTheme(TeamScopedRootMixin, UUIDModel):
    """A broad cluster of one scanner's issue observations, named as a search the Search tab suggests."""

    # The scanner and recency index serves every read, so the foreign key needs no index of its own.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="+", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=128, blank=True, default="")
    # The member count that triggers the next naming, so a theme is renamed as it grows rather than on every member.
    rename_at_member_count = models.PositiveIntegerField(default=THEME_FIRST_RENAME_AT)
    last_member_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "replay_vision"
        indexes = [models.Index(fields=["scanner", "-last_member_at"], name="rv_theme_scanner_recent_idx")]


class ReplayScannerFeedGroup(TeamScopedRootMixin, UUIDModel):
    """A tight cluster of one scanner's issue observations that tell the same story, shown as one feed card."""

    # The scanner and recency index serves every read, so the foreign key needs no index of its own.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="+", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)
    last_member_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "replay_vision"
        indexes = [models.Index(fields=["scanner", "-last_member_at"], name="rv_feed_group_recent_idx")]
