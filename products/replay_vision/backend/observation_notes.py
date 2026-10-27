"""Deleting the notes on observations that go away with their scanner.

Notes are generic comments keyed by observation id, so no foreign key cascades them. The receiver sits on
the scanner, not the observation, because a per-observation receiver would add one query for each
observation in a scanner delete. A retry deletes only failed or ineligible rows, which cannot have notes,
and a team delete cascades comments through the team.
"""

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.comment import Comment
from posthog.models.comment.comment import OBSERVATION_COMMENT_SCOPES

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scanner_access import is_uuid


@receiver(pre_delete, sender=ReplayScanner)
def delete_scanner_observation_notes(sender: type[ReplayScanner], instance: ReplayScanner, **kwargs: object) -> None:
    # Notes are few, so read them first and match only their observations rather than the scanner's.
    notes = Comment.objects.filter(team_id=instance.team_id, scope__in=OBSERVATION_COMMENT_SCOPES)
    note_item_ids = set(notes.values_list("item_id", flat=True))
    if not note_item_ids:
        return
    scanner_observation_ids = {
        str(observation_id)
        for observation_id in ReplayObservation.objects.filter(
            team_id=instance.team_id,
            scanner_id=instance.id,
            id__in=[item_id for item_id in note_item_ids if is_uuid(item_id)],
        ).values_list("id", flat=True)
    }
    if scanner_observation_ids:
        notes.filter(item_id__in=scanner_observation_ids).delete()
