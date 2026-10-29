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


class ReplayScannerFeedGroupDay(TeamScopedRootMixin, models.Model):
    """One feed group's members that joined on one UTC day, per experiment variant, so trends read a few rows."""

    group = models.ForeignKey(
        "replay_vision.ReplayScannerFeedGroup", on_delete=models.CASCADE, related_name="days", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    day = models.DateField()
    # Empty for a member with no attributed variant.
    variant = models.CharField(max_length=400, blank=True, default="")
    # Zero for a member scanned without experiment targeting, so reads can leave out experiments a viewer can't open.
    experiment_id = models.BigIntegerField(default=0)
    observation_count = models.PositiveIntegerField(default=0)
    issue_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "replay_vision"
        constraints = [
            models.UniqueConstraint(
                fields=["group", "day", "variant", "experiment_id"], name="rv_feed_group_day_unique"
            )
        ]


class ReplayScannerSearchThemeDay(TeamScopedRootMixin, models.Model):
    """One search theme's members that joined on one UTC day; themes hold no experiment rows, so no variant."""

    theme = models.ForeignKey(
        "replay_vision.ReplayScannerSearchTheme", on_delete=models.CASCADE, related_name="days", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    day = models.DateField()
    observation_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "replay_vision"
        constraints = [models.UniqueConstraint(fields=["theme", "day"], name="rv_search_theme_day_unique")]
