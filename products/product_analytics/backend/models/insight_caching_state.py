from django.db import models
from django.db.models.signals import post_save

from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.signals import mutable_receiver
from posthog.models.utils import UniqueConstraintByExpression, UUIDTModel

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight


class InsightCachingState(UUIDTModel):
    class Meta:
        indexes = [models.Index(fields=["cache_key"], name="filter_by_cache_key_idx")]
        constraints = [
            UniqueConstraintByExpression(
                name="unique_insight_tile_idx",
                expression="(insight_id, coalesce(dashboard_tile_id, -1))",
            )
        ]
        db_table = "posthog_insightcachingstate"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    insight = models.ForeignKey(
        "product_analytics.Insight",
        on_delete=models.CASCADE,
        related_name="caching_states",
        null=False,
    )
    dashboard_tile = models.ForeignKey(
        "dashboards.DashboardTile",
        on_delete=models.CASCADE,
        related_name="caching_states",
        null=True,
    )
    cache_key = models.CharField(max_length=400, null=False, blank=False)

    target_cache_age_seconds = models.IntegerField(null=True)

    last_refresh = models.DateTimeField(blank=True, null=True)
    last_refresh_queued_at = models.DateTimeField(blank=True, null=True)
    refresh_attempt = models.IntegerField(null=False, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


def _queue_sync_insight_caching_state(team_id: int, **kwargs: int | None) -> None:
    # posthog.tasks.__init__ eagerly imports every task module (celery autoimport), so a
    # module-level import here would pull the whole task graph into django.setup() via models.
    from posthog.tasks.tasks import sync_insight_caching_state  # noqa: PLC0415

    sync_insight_caching_state.delay(team_id, **kwargs)


@mutable_receiver(post_save, sender=SharingConfiguration)
def sync_sharing_configuration(sender, instance: SharingConfiguration, **kwargs):
    if instance.insight is not None and not instance.insight.deleted:
        _queue_sync_insight_caching_state(instance.team_id, insight_id=instance.insight_id)
    elif instance.dashboard is not None and not instance.dashboard.deleted:
        for tile in instance.dashboard.tiles.all():
            _queue_sync_insight_caching_state(instance.team_id, dashboard_tile_id=tile.pk)


@mutable_receiver(post_save, sender=Insight)
def sync_insight(sender, instance: Insight, **kwargs):
    _queue_sync_insight_caching_state(instance.team_id, insight_id=instance.pk)


@mutable_receiver(post_save, sender=DashboardTile)
def sync_dashboard_tile(sender, instance: DashboardTile, **kwargs):
    # Use the denormalized team_id (always populated in DashboardTile.save() before this
    # signal fires) rather than instance.dashboard.team_id, which triggers a DB fetch of the
    # dashboard row on every tile save.
    _queue_sync_insight_caching_state(instance.team_id, dashboard_tile_id=instance.pk)


@mutable_receiver(post_save, sender=Dashboard)
def sync_dashboard_updated(sender, instance: Dashboard, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields in [
        frozenset({"filters_hash"}),
        frozenset({"last_refresh"}),
        frozenset({"last_accessed_at"}),
    ]:
        return

    for tile_id in DashboardTile.objects.filter(dashboard=instance).values_list("pk", flat=True):
        _queue_sync_insight_caching_state(instance.team_id, dashboard_tile_id=tile_id)
