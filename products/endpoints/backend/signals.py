from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from products.data_modeling.backend.facade.api import endpoint_link
from products.data_modeling.backend.facade.models import Node, NodeType
from products.endpoints.backend.models import EndpointVersion


def _clear_endpoint_cache(team_id: int, name: str, version: int) -> None:
    # The rate limiter imports query strategies, which must stay out of Django startup.
    from products.endpoints.backend.rate_limit import clear_endpoint_materialization_cache  # noqa: PLC0415

    clear_endpoint_materialization_cache(team_id, name, versions=[version])


@receiver(post_save, sender=Node)
@receiver(post_delete, sender=Node)
def invalidate_endpoint_node_cache(sender: type[Node], instance: Node, **kwargs: object) -> None:
    link = endpoint_link(instance.properties)
    if link is not None:
        # robust: a Redis failure must not skip the schedule reconciliation callbacks registered after this one.
        transaction.on_commit(lambda: _clear_endpoint_cache(instance.team_id, link.name, link.version), robust=True)
    elif instance.type == NodeType.ENDPOINT and instance.saved_query_id is not None:

        def clear_legacy_endpoint_cache() -> None:
            for name, version in EndpointVersion.objects.filter(
                endpoint__team_id=instance.team_id, saved_query_id=instance.saved_query_id
            ).values_list("endpoint__name", "version"):
                _clear_endpoint_cache(instance.team_id, name, version)

        transaction.on_commit(clear_legacy_endpoint_cache, robust=True)
