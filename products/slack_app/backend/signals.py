from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.integration import Integration


@receiver(post_save, sender=Integration)
@receiver(post_delete, sender=Integration)
def invalidate_repo_list_on_github_change(sender: Any, instance: Integration, **kwargs) -> None:
    if instance.kind != "github":
        return
    # Deferred: products.slack_app.backend.api imports posthog.temporal.ai workflows at module
    # scope, which pulls the whole ee.hogai chat-agent core. This receiver is wired from
    # AppConfig.ready(), so a module-level import would drag the AI core into every process's
    # startup. The cache helper is only needed when a GitHub integration actually changes.
    from products.slack_app.backend.api import _invalidate_repo_list_cache  # noqa: PLC0415

    _invalidate_repo_list_cache(instance.team_id)
