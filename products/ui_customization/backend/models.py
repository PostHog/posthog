from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7


class UserInterfaceFragment(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.BigIntegerField()
    context = models.CharField(max_length=128)
    content = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team_id", "user_id", "context"], name="ui_fragment_unique_context"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.context}"
