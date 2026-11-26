from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import PersonalApiKeyRateThrottle

from products.workflows.backend.facade.advent_calendar import (
    ADVENT_CALENDAR_QUESTIONS,
    advent_calendar_results,
    answer_advent_calendar,
)
from products.workflows.backend.facade.contracts import AdventCalendarQuestionResult
from products.workflows.backend.facade.enums import AdventCalendarDay, AdventCalendarOption


class AdventCalendarAnswerSerializer(serializers.Serializer):
    day = serializers.ChoiceField(
        choices=AdventCalendarDay.choices, help_text="The calendar day of the question the person answers."
    )
    option = serializers.ChoiceField(
        choices=AdventCalendarOption.choices,
        help_text="The option the person picks. It must be one of the two options of that day's question.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        day = AdventCalendarDay(attrs["day"])
        option = AdventCalendarOption(attrs["option"])
        if option not in ADVENT_CALENDAR_QUESTIONS.get(day, ()):
            raise serializers.ValidationError({"option": f"Day {day.value} has no option {option.value!r}."})
        return {"day": day, "option": option}


class AdventCalendarShareSerializer(serializers.Serializer):
    option = serializers.ChoiceField(choices=AdventCalendarOption.choices, help_text="One option of the question.")
    share = serializers.IntegerField(
        help_text="Percent of all answers to the question that picked this option, rounded to a whole number. "
        "0 for every option while the question has no answers."
    )


class AdventCalendarQuestionResultSerializer(serializers.Serializer):
    day = serializers.ChoiceField(choices=AdventCalendarDay.choices, help_text="The calendar day of the question.")
    answer = serializers.ChoiceField(
        choices=AdventCalendarOption.choices,
        allow_null=True,
        help_text="The option the signed-in person picked, or null when they have not answered this question.",
    )
    shares = AdventCalendarShareSerializer(
        many=True, help_text="Each option of the question, in the calendar's order, with its share of all answers."
    )


class AdventCalendarResultsSerializer(serializers.Serializer):
    questions = AdventCalendarQuestionResultSerializer(
        many=True,
        help_text="Every advent calendar question, by day. Shares count the answers of every user of this PostHog "
        "instance, not only this project's members. Each cloud region counts its own users.",
    )


class AdventCalendarUserThrottle(PersonalApiKeyRateThrottle):
    scope = "workflow_advent_calendar_user"
    rate = "30/minute"
    reads_history_from_primary = True

    def allow_request(self, request: Request, view: Any) -> bool:
        return self._would_allow(request, view)

    def get_cache_key(self, request: Request, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class WorkflowAdventCalendarViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """How people answer the questions of the Workflows advent calendar."""

    scope_object = "INTERNAL"
    posthog_feature_flag = "workflows-advent-calendar"
    permission_classes = [PostHogFeatureFlagPermission]

    def get_throttles(self) -> list[BaseThrottle]:
        return [AdventCalendarUserThrottle(), *super().get_throttles()]

    @extend_schema(operation_id="workflow_advent_calendar_results", responses={200: AdventCalendarResultsSerializer})
    @action(detail=False, methods=["get"])
    def results(self, request: Request, **kwargs: Any) -> Response:
        return self._results_response(advent_calendar_results(cast(User, request.user).id))

    @validated_request(
        request_serializer=AdventCalendarAnswerSerializer,
        responses={200: AdventCalendarResultsSerializer},
        operation_id="workflow_advent_calendar_answer",
    )
    @action(detail=False, methods=["post"])
    def answer(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return self._results_response(
            answer_advent_calendar(
                cast(User, request.user).id, request.validated_data["day"], request.validated_data["option"]
            )
        )

    def _results_response(self, questions: list[AdventCalendarQuestionResult]) -> Response:
        return Response(AdventCalendarResultsSerializer({"questions": questions}).data)
