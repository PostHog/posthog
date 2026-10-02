"""Clears a team's cross-scanner search suggestions when a scanner that fed them is deleted. Clearing the
watermark too makes the team due again, so the next refresh draws on the scanners that remain.

A receiver rather than a call at each deletion site: Django sends `post_delete` per instance for cascaded and
queryset deletes alike, so every path that deletes a scanner is covered.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.team_replay_vision_config import TeamReplayVisionConfig


@receiver(post_delete, sender=ReplayScanner)
def forget_team_suggestions_from_deleted_scanner(
    sender: type[ReplayScanner], instance: ReplayScanner, **kwargs: object
) -> None:
    TeamReplayVisionConfig.objects.filter(
        team_id=instance.team_id, search_suggestions_sources__contains=[str(instance.id)]
    ).update(
        search_suggestions=[],
        search_suggestions_sources=[],
        search_suggestions_watermark=None,
        search_suggestions_generated_at=None,
    )
