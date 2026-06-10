from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.api import _invalidate_user_repo_list_cache


@receiver(post_save, sender=UserIntegration)
@receiver(post_delete, sender=UserIntegration)
def invalidate_repo_list_on_user_github_change(sender: Any, instance: UserIntegration, **kwargs) -> None:
    if instance.kind == UserIntegration.IntegrationKind.GITHUB:
        _invalidate_user_repo_list_cache(instance.user_id)
