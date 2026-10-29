from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

# A theme waits for this many members before its first name, so a one-off session never costs a model call.
THEME_FIRST_RENAME_AT = 5
# A group is narrower than a theme, so it waits for more members before a model names it.
GROUP_FIRST_RENAME_AT = 10


class ClusterReview(models.TextChoices):
    """What a person decided about a cluster. A cluster nobody reviewed has an empty state."""

    KNOWN = "known", "Known"
    RESOLVED = "resolved", "Resolved"
    NOT_AN_ISSUE = "not_an_issue", "Not an issue"


class ClusterReviewMixin(models.Model):
    """A person's decision about a cluster. A reviewed cluster is never pruned, so the decision outlives quiet spells."""

    # Database defaults let a consumer still on the old release insert clusters while the new one rolls out.
    review_state = models.CharField(max_length=16, choices=ClusterReview.choices, blank=True, default="", db_default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )

    class Meta:
        abstract = True


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


class ReplayScannerSearchTheme(TeamScopedRootMixin, ClusterReviewMixin, UUIDModel):
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


class ReplayScannerFeedGroup(TeamScopedRootMixin, ClusterReviewMixin, UUIDModel):
    """A tight cluster of one scanner's issue observations that tell the same story, shown as one feed card."""

    # The scanner and recency index serves every read, so the foreign key needs no index of its own.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="+", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)
    # A short headline of what the members share, written once the group is large enough to be worth a model call.
    name = models.CharField(max_length=128, blank=True, default="", db_default="")
    rename_at_member_count = models.PositiveIntegerField(
        default=GROUP_FIRST_RENAME_AT, db_default=GROUP_FIRST_RENAME_AT
    )
    last_member_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "replay_vision"
        indexes = [models.Index(fields=["scanner", "-last_member_at"], name="rv_feed_group_recent_idx")]


class ReplayScannerFeedGroupDay(TeamScopedRootMixin, models.Model):
    """One feed group's members that joined on one UTC day, per category and experiment variant, so trends and the
    feed's ranking read a few rows per group instead of every member."""

    group = models.ForeignKey(
        "replay_vision.ReplayScannerFeedGroup", on_delete=models.CASCADE, related_name="days", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    day = models.DateField()
    # Empty for a member with no attributed variant.
    variant = models.CharField(max_length=400, blank=True, default="")
    # Zero for a member scanned without experiment targeting, so reads can leave out experiments a viewer can't open.
    experiment_id = models.BigIntegerField(default=0)
    # The members' feed category, so counts and ranking can keep to the categories a reader asked for.
    category = models.CharField(max_length=16)
    observation_count = models.PositiveIntegerField(default=0)
    # The day's highest feed score among these members, which ranks the group without reading them.
    best_contrast = models.FloatField()

    class Meta:
        app_label = "replay_vision"
        constraints = [
            models.UniqueConstraint(
                fields=["group", "day", "variant", "experiment_id", "category"], name="rv_feed_group_day_unique"
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
