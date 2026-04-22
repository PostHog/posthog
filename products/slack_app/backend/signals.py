from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.integration import Integration

from products.slack_app.backend.api import _invalidate_repo_list_cache


@receiver(post_save, sender=Integration)
@receiver(post_delete, sender=Integration)
def invalidate_repo_list_on_github_change(sender, instance: Integration, **kwargs) -> None:
    if instance.kind == "github":
        _invalidate_repo_list_cache(instance.team_id)
