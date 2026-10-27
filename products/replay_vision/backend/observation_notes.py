"""Deleting the notes on observations that go away with their scanner.

Notes are generic comments keyed by observation id, so no foreign key cascades them. The receiver sits on
the scanner, not the observation, because a per-observation receiver would add one query for each
observation in a scanner delete. A retry deletes only failed or ineligible rows, which cannot have notes,
and a team delete cascades comments through the team.
"""

from django.db.models import CharField
from django.db.models.functions import Cast
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.comment import Comment
from posthog.models.comment.comment import OBSERVATION_COMMENT_SCOPES

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner


@receiver(pre_delete, sender=ReplayScanner)
def delete_scanner_observation_notes(sender: type[ReplayScanner], instance: ReplayScanner, **kwargs: object) -> None:
    # Note item_ids are stored as canonical UUID text, so the scanner's observation ids match them in SQL.
    observation_ids = (
        ReplayObservation.objects.filter(team_id=instance.team_id, scanner_id=instance.id)
        .annotate(id_text=Cast("id", output_field=CharField()))
        .values("id_text")
    )
    Comment.objects.filter(
        team_id=instance.team_id, scope__in=OBSERVATION_COMMENT_SCOPES, item_id__in=observation_ids
    ).delete()
