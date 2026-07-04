import uuid
from typing import TypeVar

from django.db import transaction
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.pulse.backend.models import Opportunity, ProductBrief

TFeedbackModel = TypeVar("TFeedbackModel", Opportunity, ProductBrief)
FeedbackModel = Opportunity | ProductBrief


class FeedbackVoteRequestSerializer(serializers.Serializer):
    helpful = serializers.BooleanField(
        allow_null=True,
        help_text="True marks the item helpful, false marks it not helpful, and null clears your vote.",
    )


def _votes(feedback: dict) -> dict:
    votes = feedback.get("votes") if isinstance(feedback, dict) else None
    return votes if isinstance(votes, dict) else {}


def apply_vote(feedback: dict, user_id: int, helpful: bool | None) -> dict:
    """Return the feedback JSON with the caller's vote overwritten, or removed for a null vote."""
    votes = dict(_votes(feedback))
    key = str(user_id)
    if helpful is None:
        votes.pop(key, None)
    else:
        votes[key] = {"helpful": helpful, "at": timezone.now().isoformat()}
    return {**(feedback if isinstance(feedback, dict) else {}), "votes": votes}


def record_vote(
    model: type[TFeedbackModel], team_id: int, pk: uuid.UUID, user_id: int, helpful: bool | None
) -> TFeedbackModel:
    """Apply one user's vote under a row lock, so concurrent voters can't clobber each other's
    read-modify-write of the shared votes dict."""
    with transaction.atomic():
        instance = model.objects.for_team(team_id).select_for_update().get(pk=pk)
        instance.feedback = apply_vote(instance.feedback, user_id, helpful)
        # auto_now only persists when updated_at is listed explicitly alongside the change.
        instance.save(update_fields=["feedback", "updated_at"])
    return instance


class FeedbackFieldsSerializerMixin(serializers.Serializer):
    """Derived, leak-free view of the feedback votes: team-wide counts plus the caller's own vote.

    The raw votes dict is keyed by user id and is never serialized — no identity beyond counts
    crosses the API boundary.
    """

    my_vote = serializers.SerializerMethodField(
        help_text="The calling user's helpfulness vote: true, false, or null when they have not voted."
    )
    helpful_count = serializers.SerializerMethodField(help_text="Number of helpful votes across the team.")
    not_helpful_count = serializers.SerializerMethodField(help_text="Number of not-helpful votes across the team.")

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_my_vote(self, obj: FeedbackModel) -> bool | None:
        request = self.context.get("request")
        user_id = getattr(getattr(request, "user", None), "id", None)
        if user_id is None:
            return None
        vote = _votes(obj.feedback).get(str(user_id))
        helpful = vote.get("helpful") if isinstance(vote, dict) else None
        return helpful if isinstance(helpful, bool) else None

    def get_helpful_count(self, obj: FeedbackModel) -> int:
        return self._count_votes(obj, helpful=True)

    def get_not_helpful_count(self, obj: FeedbackModel) -> int:
        return self._count_votes(obj, helpful=False)

    def _count_votes(self, obj: FeedbackModel, helpful: bool) -> int:
        return sum(
            1 for vote in _votes(obj.feedback).values() if isinstance(vote, dict) and vote.get("helpful") is helpful
        )
