from django.db import models

from posthog.models.utils import UUIDTModel


class MessageCategoryType(models.TextChoices):
    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"


class MessageCategory(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    deleted = models.BooleanField(default=False)
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    public_description = models.TextField(blank=True, default="")
    category_type = models.CharField(
        max_length=32, choices=MessageCategoryType, default=MessageCategoryType.MARKETING.value
    )

    class Meta:
        unique_together = (
            "team",
            "key",
        )
        verbose_name_plural = "message categories"
        db_table = "posthog_messagecategory"

    def __str__(self) -> str:
        return self.name


class MessageCategoryImportKey(UUIDTModel):
    """An imported category that was matched to an existing category by name, so a later rename doesn't split it."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    key = models.CharField(max_length=64)
    category = models.ForeignKey(MessageCategory, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name="unique_message_category_import_key_per_team"),
        ]
