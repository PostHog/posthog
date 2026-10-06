from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDTModel


class MessageCategoryType(models.TextChoices):
    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"


class MessageCategory(CreatedMetaFields, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)
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
