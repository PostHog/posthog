from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.posthog_ai.backend.turn_suggestions.offer_ledger import TurnSuggestionResolution
from products.posthog_ai.backend.turn_suggestions.service import resolve_turn_suggestion
from products.tasks.backend.facade.api import task_visible


class ResolveTurnSuggestionSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(
        help_text="ID of the PostHog AI conversation (task) the suggestion card belongs to."
    )
    turn_index = serializers.IntegerField(
        min_value=0, help_text="Zero-based index of the conversation turn the suggestion card was shown under."
    )
    resolution = serializers.ChoiceField(
        choices=TurnSuggestionResolution.choices,
        help_text="What the user did with the card: `dismissed` mutes suggestions for the rest of the conversation, `accepted` means the offered scout, notebook, alert or subscription was created.",
    )


class ResolveTurnSuggestionResponseSerializer(serializers.Serializer):
    recorded = serializers.BooleanField(
        help_text="Whether a suggestion card existed for that turn and this call recorded its outcome. A card keeps the first outcome recorded for it."
    )


class TurnSuggestionsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "task"

    @validated_request(
        request_serializer=ResolveTurnSuggestionSerializer,
        responses={200: OpenApiResponse(response=ResolveTurnSuggestionResponseSerializer)},
        summary="Record what the user did with a PostHog AI turn suggestion card",
    )
    @action(detail=False, methods=["post"], required_scopes=["task:write"])
    def resolve(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        task_id = str(request.validated_data["task_id"])
        # A dismissal mutes the conversation for its creator, so a teammate who can only read it must not resolve cards.
        if not task_visible(task_id, self.team_id, request.user.id, for_control=True):
            raise NotFound()
        recorded = resolve_turn_suggestion(
            task_id,
            self.team_id,
            turn_index=request.validated_data["turn_index"],
            resolution=TurnSuggestionResolution(request.validated_data["resolution"]),
        )
        return Response(ResolveTurnSuggestionResponseSerializer({"recorded": recorded}).data)
