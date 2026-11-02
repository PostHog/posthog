from django.db import models

from posthog.models.tagged_items_relation import Taggable
from posthog.models.utils import UUIDTModel


# nosemgrep: no-new-uuidt-models -- an existing model, and its stored ids cannot change.
class MessageTemplate(Taggable, UUIDTModel):
    """
    A model for storing message templates used for email and eventually other messaging channels.
    """

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
    # Unpublished edits to a transactional template. Sends keep using `content` until the draft is published.
    draft_content = models.JSONField(null=True, blank=True)
    # For emails carrying codes or reset links: sends keep no rendered body or subject, and clicks keep only
    # the link's origin.
    sensitive = models.BooleanField(default=False, db_default=False)

    class Meta:
        db_table = "posthog_messagetemplate"

    def __str__(self):
        return self.name
