from typing import Optional

from django.db import models, router
from django.db.models import F, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.utils import UUIDTModel

ALL_MESSAGE_PREFERENCE_CATEGORY_ID = "$all"

# Reserved preference key for open/click tracking consent (CNIL/ePrivacy). Distinct from the
# '$all' unsubscribe: a recipient can keep receiving emails while refusing open/click tracking.
# Mirrored in nodejs/src/cdp/services/managers/recipients-manager.service.ts.
EMAIL_TRACKING_PREFERENCE_ID = "$email_tracking"


class PreferenceStatus(models.TextChoices):
    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    NO_PREFERENCE = "NO_PREFERENCE"


class MessageRecipientPreference(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    deleted = models.BooleanField(default=False)
    identifier = models.CharField(max_length=512)
    preferences = models.JSONField(default=dict)

    class Meta:
        unique_together = (
            "team",
            "identifier",
        )
        db_table = "posthog_messagerecipientpreference"

    def __str__(self) -> str:
        return f"Preferences for {self.identifier}"

    def set_preference(self, category_id: str, status: PreferenceStatus) -> None:
        """Set preference for a specific category"""
        if not isinstance(status, PreferenceStatus):
            raise ValueError(f"Status must be a PreferenceStatus enum, got {type(status)}")

        # Merge the one key in the database. Saving the whole column would drop a category that another request
        # set after this row was read.
        type(self).objects.filter(pk=self.pk, team_id=self.team_id).update(
            preferences=CombinedExpression(
                Coalesce(F("preferences"), Value({}, output_field=models.JSONField())),
                "||",
                Value({str(category_id): status.value}, output_field=models.JSONField()),
            ),
            updated_at=timezone.now(),
        )
        self.refresh_from_db(using=router.db_for_write(type(self)), fields=["preferences", "updated_at"])

    def get_preference(self, category_id: str) -> PreferenceStatus:
        """Get preference for a specific category"""
        status = self.preferences.get(str(category_id), PreferenceStatus.NO_PREFERENCE.value)
        return PreferenceStatus(status)

    def get_all_preferences(self) -> dict[str, PreferenceStatus]:
        """Get all preferences as a dictionary of UUID to PreferenceStatus"""
        """Get all preferences as a dictionary of category ID to PreferenceStatus"""
        return {str(category_id): PreferenceStatus(status) for category_id, status in self.preferences.items()}

    @classmethod
    def get_or_create_for_identifier(
        cls, team_id: int, identifier: str, defaults: Optional[dict[str, PreferenceStatus]] = None
    ) -> "MessageRecipientPreference":
        """Get or create preferences for an identifier"""
        if defaults is None:
            defaults = {}

        preferences_dict = {str(category_id): status.value for category_id, status in defaults.items()}

        instance, _ = cls.objects.get_or_create(
            team_id=team_id, identifier=identifier, defaults={"preferences": preferences_dict}
        )
        return instance
