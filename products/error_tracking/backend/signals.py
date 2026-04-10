from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from posthog.models.team.team import Team

from products.error_tracking.backend.recommendations import ALL_RECOMMENDATIONS
from products.error_tracking.backend.tasks import run_error_tracking_recommendation

# Union of every Team field any recommendation cares about. We snapshot these
# in pre_save so we can diff them in post_save without issuing an extra query.
_WATCHED_TEAM_FIELDS: frozenset[str] = frozenset(
    field for recommendation in ALL_RECOMMENDATIONS for field in recommendation.watched_team_fields
)

_SNAPSHOT_ATTR = "_error_tracking_recommendations_prev"


@receiver(pre_save, sender=Team)
def snapshot_team_watched_fields(sender, instance: Team, **kwargs) -> None:
    if not _WATCHED_TEAM_FIELDS or instance.pk is None or instance._state.adding:
        return
    try:
        previous = Team.objects.only(*_WATCHED_TEAM_FIELDS).get(pk=instance.pk)
    except Team.DoesNotExist:
        return
    setattr(
        instance,
        _SNAPSHOT_ATTR,
        {field: getattr(previous, field) for field in _WATCHED_TEAM_FIELDS},
    )


@receiver(post_save, sender=Team)
def run_recommendations_on_team_change(sender, instance: Team, created: bool, **kwargs) -> None:
    if not ALL_RECOMMENDATIONS:
        return

    previous: dict | None = getattr(instance, _SNAPSHOT_ATTR, None)

    recommendations_to_run: list[str] = []
    for recommendation in ALL_RECOMMENDATIONS:
        if not recommendation.watched_team_fields:
            continue
        if created or previous is None:
            recommendations_to_run.append(recommendation.type)
            continue
        if any(getattr(instance, field) != previous.get(field) for field in recommendation.watched_team_fields):
            recommendations_to_run.append(recommendation.type)

    if not recommendations_to_run:
        return

    team_id = instance.id

    def dispatch() -> None:
        for recommendation_type in recommendations_to_run:
            run_error_tracking_recommendation.delay(team_id, recommendation_type)

    transaction.on_commit(dispatch)
