from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class EmailBrand(TeamScopedRootMixin, UUIDModel):
    """The brand a project's branded email starter is built from. One row per project, shared by its environments."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        WEBSITE = "website", "Website"
        GITHUB = "github", "GitHub"

    # db_constraint=False: a real FK constraint to posthog_team or posthog_user locks that hot table on creation.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255, blank=True, default="")
    primary_color = models.CharField(max_length=7, default="#1d4aff")
    logo_url = models.CharField(max_length=2048, null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
