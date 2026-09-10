import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from .facade.enums import Effect, Scope, TargetType


# Callables, so a new member adds no migration. Django resolves them lazily and the
# migration records only the function path, so keep these names and this module.
def target_type_choices() -> list[tuple[str, str]]:
    return [(target_type.value, target_type.value) for target_type in TargetType]


def effect_choices() -> list[tuple[str, str]]:
    return [(effect.value, effect.value) for effect in Effect]


def scope_choices() -> list[tuple[str, str]]:
    return [(scope.value, scope.value) for scope in Scope]


class SecurityRuleQuerySet(models.QuerySet):
    def active(self) -> "SecurityRuleQuerySet":
        now = timezone.now()
        return self.filter(revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


class SecurityRule(models.Model):
    """A target plus what happens to it. Instance-global: a rule has no team, and each
    region's database holds its own rules."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_type = models.CharField(max_length=32, choices=target_type_choices)
    # Stored normalized, so equality is the match for every exact-match target type.
    target_value = models.CharField(max_length=320)
    effect = models.CharField(max_length=16, choices=effect_choices)
    scope = models.CharField(max_length=32, choices=scope_choices)
    reason = models.TextField()
    # db_constraint=False on both user links: a constraint to posthog_user locks that hot
    # table under write traffic when the migration adds it. The link is authorship only.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Revoked rather than deleted, so the record of who blocked what survives.
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    objects = SecurityRuleQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_value", "effect", "scope"],
                condition=Q(revoked_at__isnull=True),
                name="security_rule_unique_unrevoked",
            )
        ]

    def __str__(self) -> str:
        return f"{self.effect} {self.scope}: {self.target_type} {self.target_value}"

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()
