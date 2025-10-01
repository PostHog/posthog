from django.db import models

from posthog.models.utils import UUIDModel


class FeedbackItem(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="feedback_items",
        related_query_name="feedback_item",
    )
    category = models.ForeignKey(
        "FeedbackItemCategory",
        on_delete=models.CASCADE,
        related_name="feedback_items",
        related_query_name="feedback_item",
        null=True,
    )
    topic = models.ForeignKey(
        "FeedbackItemTopic",
        on_delete=models.CASCADE,
        related_name="feedback_items",
        related_query_name="feedback_item",
        null=True,
    )
    content = models.TextField(blank=False)
    created_at = models.DateTimeField(auto_now_add=True)


class FeedbackItemAttachment(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
    )
    feedback_item = models.ForeignKey(
        "FeedbackItem",
        on_delete=models.CASCADE,
        related_name="attachments",
        related_query_name="attachment",
    )
    storage_ptr = models.TextField(null=True, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)


class FeedbackItemCategory(UUIDModel):
    name = models.CharField(max_length=200)
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="feedback_item_categories",
        related_query_name="feedback_item_category",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class FeedbackItemTopic(UUIDModel):
    name = models.CharField(max_length=200)
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="feedback_item_topics",
        related_query_name="feedback_item_topic",
    )
    created_at = models.DateTimeField(auto_now_add=True)
