from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

DEFAULT_TEXT_COLOR = "#111111"
DEFAULT_BACKGROUND_COLOR = "#ffffff"
DEFAULT_FONT_FAMILY = "Arial"
DEFAULT_FONT_STACK = "Arial, Helvetica, sans-serif"


class EmailBrand(TeamScopedRootMixin, UUIDModel):
    """The one brand a project's emails are styled with, detected from its GitHub repo or entered by hand.

    The one-to-one team link plus the canonical-team rewrite on save make it one row per project,
    shared by all of the project's environments. Behind the `workflows-brand-detection` flag.
    """

    SOURCED_FIELDS = (
        "name",
        "logo",
        "primary_color",
        "accent_color",
        "text_color",
        "background_color",
        "font_family",
    )
    COLOR_FIELDS = ("primary_color", "accent_color", "text_color", "background_color")

    # db_constraint=False on team/created_by: a real FK constraint to a hot table
    # (posthog_team, posthog_user) takes a parent-table lock on creation; enforcement stays app-level.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255, blank=True, default="")
    logo = models.ForeignKey(
        "posthog.UploadedMedia", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    primary_color = models.CharField(max_length=7, default=DEFAULT_TEXT_COLOR)
    accent_color = models.CharField(max_length=7, default=DEFAULT_TEXT_COLOR)
    text_color = models.CharField(max_length=7, default=DEFAULT_TEXT_COLOR)
    background_color = models.CharField(max_length=7, default=DEFAULT_BACKGROUND_COLOR)
    font_family = models.CharField(max_length=100, default=DEFAULT_FONT_FAMILY)
    font_stack = models.CharField(max_length=500, default=DEFAULT_FONT_STACK)

    source_repository = models.CharField(max_length=255, blank=True, default="")
    app_root = models.CharField(max_length=255, blank=True, default="")
    sources = models.JSONField(default=dict, blank=True)

    def edited_fields(self) -> dict[str, bool]:
        return {field: self._is_edited(field) for field in self.SOURCED_FIELDS}

    def _is_edited(self, field: str) -> bool:
        source = self.sources.get(field)
        if source is None:
            return False
        return self._comparable_value(field) != source.get("detected_value")

    def _comparable_value(self, field: str) -> str | None:
        if field == "logo":
            return str(self.logo_id) if self.logo_id else None
        return getattr(self, field)
