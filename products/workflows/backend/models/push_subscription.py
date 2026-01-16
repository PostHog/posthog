import hashlib

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.utils import UUIDModel


class PushPlatform(models.TextChoices):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class PushSubscription(UUIDModel):
    """
    Stores push notification tokens for devices.
    Tokens are stored here (not as person properties) for security - person properties
    are readable via API, but FCM tokens should not be exposed.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    distinct_id = models.CharField(max_length=512)

    # FCM token or APNs device token
    token = EncryptedTextField()
    token_hash = models.CharField(max_length=64)

    platform = models.CharField(max_length=16, choices=PushPlatform.choices)

    is_active = models.BooleanField(default=True, db_index=True)

    last_successfully_used_at = models.DateTimeField(null=True, blank=True)

    disabled_reason = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "distinct_id", "is_active"]),
            models.Index(fields=["team", "token_hash"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "distinct_id", "token_hash"],
                name="unique_team_distinct_id_token_hash",
            )
        ]

    def __str__(self) -> str:
        return f"PushSubscription({self.distinct_id}, {self.platform}, active={self.is_active})"

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs) -> None:
        # Keep `token_hash` in sync even if saved outside `upsert_token`.
        if self.token:
            self.token_hash = self._hash_token(self.token)
        super().save(*args, **kwargs)

    @classmethod
    def upsert_token(
        cls,
        team_id: int,
        distinct_id: str,
        token: str,
        platform: PushPlatform,
    ) -> "PushSubscription":
        """
        Create or update a push subscription token.
        If a subscription with the same team/token exists, updates it.
        """
        token_hash = cls._hash_token(token)

        subscription, _created = cls.objects.update_or_create(
            team_id=team_id,
            distinct_id=distinct_id,
            token_hash=token_hash,
            defaults={
                "token": token,
                "platform": platform,
                "is_active": True,
                "disabled_reason": None,
            },
        )

        return subscription

    @classmethod
    def get_active_tokens_for_distinct_id(
        cls,
        team_id: int,
        distinct_id: str,
        platform: PushPlatform | None = None,
    ) -> list["PushSubscription"]:
        """Get all active push subscriptions for a distinct_id."""
        qs = cls.objects.filter(team_id=team_id, distinct_id=distinct_id, is_active=True)
        if platform:
            qs = qs.filter(platform=platform)
        return list(qs)

    @classmethod
    def deactivate_token(cls, team_id: int, token: str, reason: str | None = None) -> int:
        """
        Deactivate a specific token (e.g., when FCM reports it as invalid).
        Returns the number of subscriptions deactivated.
        """
        token_hash = cls._hash_token(token)
        return cls.objects.filter(team_id=team_id, token_hash=token_hash, is_active=True).update(
            is_active=False, disabled_reason=reason or "unregistered"
        )

    @classmethod
    def update_last_successfully_used_at(cls, subscription_ids: list[str]) -> int:
        """
        Update last_successfully_used_at timestamp for the given subscription IDs.
        Returns the number of subscriptions updated.
        """
        from django.utils import timezone

        if not subscription_ids:
            return 0

        return cls.objects.filter(id__in=subscription_ids).update(last_successfully_used_at=timezone.now())
