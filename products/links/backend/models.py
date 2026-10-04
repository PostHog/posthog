from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class Link(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """The links product is retired. The model stays so that Django keeps cascading team and user
    deletes into its table. A later migration removes the model and drops the table.

    The model does not use FileSystemSyncMixin. With the mixin, `link` would be a registered file
    system type again and the unfiled saver would recreate tree rows for links."""

    redirect_url = models.URLField(max_length=2048)
    short_link_domain = models.CharField(max_length=255, help_text="Domain where the short link is hosted, e.g. hog.gg")
    short_code = models.CharField(
        max_length=255, help_text="The unique code/path that identifies the short link, e.g. 'abc123'"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, help_text="Team that owns this link", related_name="+")
    description = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["short_link_domain", "short_code"], name="domain_short_code_idx"),
            models.Index(fields=["team_id"], name="team_id_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["short_link_domain", "short_code"],
                name="unique_short_link_domain_short_code",
            )
        ]
        db_table = "posthog_link"
