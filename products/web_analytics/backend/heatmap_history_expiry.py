from uuid import UUID, uuid4

from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone

from products.web_analytics.backend.heatmap_history_storage import delete_images_on_commit
from products.web_analytics.backend.models import HeatmapCaptureRequest, HeatmapScreenshotHistory, SavedHeatmap

HISTORY_INPUTS = ("url", "data_url", "target_widths", "block_consent_modals", "type", "source", "deleted")


def cancel_live_requests(*, team_id: int, heatmap_id: UUID) -> None:
    live = HeatmapCaptureRequest.objects.for_team(team_id).filter(
        heatmap_id=heatmap_id, state__in=HeatmapCaptureRequest.LIVE_STATES
    )
    request_ids = list(live.values_list("id", flat=True))
    live.filter(id__in=request_ids).update(state=HeatmapCaptureRequest.State.CANCELLED, completed_at=timezone.now())
    delete_images_on_commit(team_id, request_ids)


@receiver(post_delete, sender=HeatmapCaptureRequest)
def delete_request_images(
    sender: type[HeatmapCaptureRequest], instance: HeatmapCaptureRequest, **kwargs: object
) -> None:
    if instance.expires_at <= timezone.now():
        return
    delete_images_on_commit(instance.team_id, [instance.id])


@receiver(pre_save, sender=SavedHeatmap)
def invalidate_history(
    sender: type[SavedHeatmap], instance: SavedHeatmap, update_fields: frozenset[str] | None = None, **kwargs: object
) -> None:
    if instance._state.adding:
        instance.history_configuration_revision = uuid4()
        return
    if update_fields is not None and update_fields.isdisjoint(HISTORY_INPUTS):
        return
    previous = SavedHeatmap.objects.filter(team_id=instance.team_id, id=instance.id).values(*HISTORY_INPUTS).first()
    if previous is None or not any(previous[field] != getattr(instance, field) for field in HISTORY_INPUTS):
        return
    instance.history_configuration_revision = uuid4()
    instance.next_history_capture_at = None
    if update_fields is not None:
        SavedHeatmap.objects.filter(team_id=instance.team_id, id=instance.id).update(
            history_configuration_revision=instance.history_configuration_revision,
            next_history_capture_at=None,
        )
    if previous["url"] != instance.url or previous["data_url"] != instance.data_url or instance.deleted:
        HeatmapScreenshotHistory.objects.for_team(instance.team_id).filter(heatmap_id=instance.id).delete()
    else:
        cancel_live_requests(team_id=instance.team_id, heatmap_id=instance.id)
