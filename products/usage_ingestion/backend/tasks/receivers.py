from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from posthog.models.team.team import Team

from ..team_organization_cache import clear_team_organization_cache


def _enqueue_publish(team_id: int) -> None:
    # Deferred so django.setup() never reaches posthog.tasks.utils, whose package
    # __init__ is the celery autoimport aggregator and drags the whole task graph in.
    from .tasks import update_team_organization_cache_task  # noqa: PLC0415

    update_team_organization_cache_task.delay(team_id)


@receiver(post_save, sender=Team)
def publish_team_organization_on_save(sender: type[Team], instance: Team, **kwargs: object) -> None:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return

    transaction.on_commit(lambda: _enqueue_publish(instance.id))


@receiver(pre_delete, sender=Team)
def clear_team_organization_on_delete(sender: type[Team], instance: Team, **kwargs: object) -> None:
    clear_team_organization_cache(instance)
