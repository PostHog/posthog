from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDTModel


class MessageTemplate(UUIDTModel):
    """
    A model for storing message templates used for email and eventually other messaging channels.
    """

    class ManagedBy(models.TextChoices):
        GUI = "gui", "GUI"
        CODE = "code", "Code"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    message_category = models.ForeignKey("messaging.MessageCategory", on_delete=models.SET_NULL, null=True, blank=True)
    content = models.JSONField(default=dict)
    type = models.CharField(max_length=24, blank=True, default="email")
    deleted = models.BooleanField(default=False)
    # Set once the template is made transactional: the workflow the send API runs for it. A plain id,
    # because the workflow lives in the workflows product.
    transactional_hog_flow_id = models.UUIDField(null=True, blank=True)
    key = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="Client-chosen identifier, unique within this environment among templates that are not deleted. "
        "Letters, numbers, hyphens (-) and underscores (_) only.",
    )
    managed_by = models.CharField(
        max_length=400,
        choices=ManagedBy,
        null=True,
        blank=True,
        help_text="Who owns the template content: `gui` for the PostHog app, `code` for uploads from a repository. "
        "Empty means `gui`.",
    )
    source_repository = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="Repository the template was last uploaded from, such as `github.com/example/app`.",
    )
    source_path = models.CharField(
        max_length=400, null=True, blank=True, help_text="Path of the template file in the source repository."
    )
    source_ref = models.CharField(
        max_length=400, null=True, blank=True, help_text="Commit or branch of the last upload."
    )
    content_hash = models.CharField(
        max_length=80,
        null=True,
        blank=True,
        help_text="Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters.",
    )
    superseded_content_hashes = ArrayField(models.CharField(max_length=80), null=True, blank=True)

    class Meta:
        db_table = "posthog_messagetemplate"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "key"],
                condition=models.Q(key__isnull=False, deleted=False),
                name="unique_message_template_key_per_team",
            ),
        ]

    def __str__(self):
        return self.name
