from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingSettings, sync_autocapture_opt_in


@receiver(post_save, sender=Team)
def mirror_autocapture_opt_in_to_settings(sender, instance: Team, update_fields=None, **kwargs) -> None:
    # Skip saves that list update_fields without this one; full saves fall through.
    if update_fields is not None and "autocapture_exceptions_opt_in" not in update_fields:
        return
    sync_autocapture_opt_in(team_id=instance.pk, opt_in=instance.autocapture_exceptions_opt_in)


@receiver(post_save, sender=ErrorTrackingSettings)
def rebuild_remote_config_on_settings_save(
    sender, instance: ErrorTrackingSettings, created: bool = False, update_fields=None, **kwargs
) -> None:
    # Remote config serves autocaptureExceptions, but the settings API mirrors onto Team via a
    # queryset update() that never fires Team post_save — so the rebuild must hang off this model.
    if update_fields is not None and "autocapture_exceptions_opt_in" not in update_fields:
        return
    # Rows created with the flag unset (e.g. lazily on a settings read) don't change remote config.
    if created and not instance.autocapture_exceptions_opt_in:
        return
    from posthog.tasks.remote_config import (
        update_team_remote_config,  # noqa: PLC0415 — keeps celery task machinery off django.setup()
    )

    team_id = instance.team_id
    transaction.on_commit(lambda: update_team_remote_config.delay(team_id))
