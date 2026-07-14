import uuid
from typing import TypeVar

from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from rest_framework import serializers

from products.pulse.backend.models import FeedbackVote, Opportunity, ProductBrief

TFeedbackModel = TypeVar("TFeedbackModel", Opportunity, ProductBrief)


class FeedbackVoteRequestSerializer(serializers.Serializer):
    helpful = serializers.BooleanField(
        allow_null=True,
        help_text="True marks the item helpful, false marks it not helpful, and null clears your vote.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1000,
        help_text="Optional free-text reason for the vote. Ignored (and cleared) when the vote is cleared.",
    )


def annotate_feedback(queryset: QuerySet, team_id: int, user_id: int | None, target: str) -> QuerySet:
    """Annotate the derived, leak-free feedback fields onto a brief/opportunity queryset.

    Counts and the caller's own vote come from indexed subqueries on the votes table, so each row
    costs a couple of index lookups rather than scanning every vote. `target` is the FeedbackVote FK
    pointing back to this model ("brief" or "opportunity").
    """
    votes = FeedbackVote.objects.for_team(team_id)

    def count(*, helpful: bool) -> Coalesce:
        per_target = (
            votes.filter(**{target: OuterRef("pk")}, helpful=helpful).values(target).annotate(c=Count("*")).values("c")
        )
        return Coalesce(Subquery(per_target, output_field=IntegerField()), 0)

    # A null user (no authenticated caller) must never match orphaned SET_NULL votes — return no
    # own-vote rather than filtering on created_by_id IS NULL.
    mine = votes.none() if user_id is None else votes.filter(**{target: OuterRef("pk")}, created_by_id=user_id)
    return queryset.annotate(
        helpful_count=count(helpful=True),
        not_helpful_count=count(helpful=False),
        my_vote=Subquery(mine.values("helpful")[:1]),
        my_reason=Subquery(mine.values("reason")[:1]),
    )


def record_vote(
    model: type[TFeedbackModel],
    team_id: int,
    pk: uuid.UUID,
    user_id: int,
    helpful: bool | None,
    reason: str,
    target: str,
) -> TFeedbackModel:
    """Upsert (or clear, for null) the caller's vote and return the target with feedback annotations.

    The partial unique constraint on (voter, target) keeps one row per voter — a revote overwrites it,
    a concurrent double-vote can't duplicate it.
    """
    lookup = {f"{target}_id": pk, "created_by_id": user_id}
    if helpful is None:
        FeedbackVote.objects.for_team(team_id).filter(**lookup).delete()
    else:
        defaults = {"helpful": helpful, "reason": reason, "team_id": team_id}
        try:
            # First-vote race: two concurrent inserts, one loses the unique constraint. The savepoint
            # lets that IntegrityError roll back cleanly; the loser then re-applies its vote as an
            # update onto the row the winner just created.
            with transaction.atomic():
                FeedbackVote.objects.for_team(team_id).update_or_create(defaults=defaults, **lookup)
        except IntegrityError:
            FeedbackVote.objects.for_team(team_id).filter(**lookup).update(
                helpful=helpful, reason=reason, updated_at=timezone.now()
            )
    # created_by is nested in the response serializers, so join it; config/first_seen_brief serialize
    # as ids straight off the row and need no join.
    queryset = annotate_feedback(model.objects.for_team(team_id).select_related("created_by"), team_id, user_id, target)
    return queryset.get(pk=pk)


class FeedbackFieldsSerializerMixin(serializers.Serializer):
    """Derived, leak-free view of the votes: team-wide counts plus the caller's own vote and reason.

    Reads the annotations from annotate_feedback. Other voters' identities and reasons never serialize.
    """

    my_vote = serializers.BooleanField(
        read_only=True,
        allow_null=True,
        help_text="The calling user's helpfulness vote: true, false, or null when they have not voted.",
    )
    my_reason = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="The calling user's own reason for their vote: their text, empty when they gave none, or null when they have not voted.",
    )
    helpful_count = serializers.IntegerField(read_only=True, help_text="Number of helpful votes across the team.")
    not_helpful_count = serializers.IntegerField(
        read_only=True, help_text="Number of not-helpful votes across the team."
    )
