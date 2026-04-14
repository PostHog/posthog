from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from posthog.models.team.team import Team

from products.error_tracking.backend.recommendations.cross_sell import RECOMMENDATION_TYPE
from products.error_tracking.backend.tasks import run_error_tracking_recommendation

_SNAPSHOT_ATTR = "_error_tracking_prev_session_recording_opt_in"


@receiver(pre_save, sender=Team)
def snapshot_session_recording_opt_in(sender, instance: Team, **kwargs) -> None:
    if instance.pk is None or instance._state.adding:
        return
    try:
        previous = Team.objects.only("session_recording_opt_in").get(pk=instance.pk)
    except Team.DoesNotExist:
        return
    setattr(instance, _SNAPSHOT_ATTR, previous.session_recording_opt_in)


@receiver(post_save, sender=Team)
def recompute_cross_sell_on_replay_change(sender, instance: Team, created: bool, **kwargs) -> None:
    if created:
        return

    previous_value = getattr(instance, _SNAPSHOT_ATTR, None)
    if previous_value is None:
        return

    if instance.session_recording_opt_in != previous_value:
        team_id = instance.id

        def dispatch() -> None:
            run_error_tracking_recommendation.delay(team_id, RECOMMENDATION_TYPE)

        transaction.on_commit(dispatch)
