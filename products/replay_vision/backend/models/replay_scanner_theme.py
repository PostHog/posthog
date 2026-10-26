from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

# A theme waits for this many members before its first name, so a one-off session never costs a model call.
THEME_FIRST_NAME_AT = 5


class ReplayScannerThemeCenter(TeamScopedRootMixin, models.Model):
    """A scanner's running sum of observation vectors. Themes compare vectors with this mean taken out, because
    every observation of one scanner shares its question's wording."""

    scanner = models.OneToOneField(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "replay_vision"


class ReplayScannerTheme(TeamScopedRootMixin, UUIDModel):
    """A cluster of one scanner's issue observations, named as a search the Search tab suggests."""

    # The scanner and recency index serves every read, so the foreign key needs no index of its own.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="themes", db_index=False
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    vector_sum = models.BinaryField()
    member_count = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=128, blank=True, default="")
    # The member count that triggers the next naming, so a theme is renamed as it grows rather than on every member.
    name_at = models.PositiveIntegerField(default=THEME_FIRST_NAME_AT)
    named_at = models.DateTimeField(null=True, blank=True)
    last_member_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "replay_vision"
        indexes = [models.Index(fields=["scanner", "-last_member_at"], name="rv_theme_scanner_recent_idx")]
