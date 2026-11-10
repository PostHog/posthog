from typing import cast

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from ..facade import api
from ..facade.contracts import UnavailableTargets
from ..facade.enums import CustomizationContext
from .serializers import (
    CustomizationDescriptionSerializer,
    CustomizationRequestSerializer,
    CustomizationSerializer,
    layout_error_detail,
)


class CustomizationBurstThrottle(UserRateThrottle):
    scope = "ui_customization_burst"
    rate = "30/minute"


class CustomizationSustainedThrottle(UserRateThrottle):
    scope = "ui_customization_sustained"
    rate = "300/day"


CUSTOMIZATION_THROTTLES = [
    BurstRateThrottle,
    SustainedRateThrottle,
    CustomizationBurstThrottle,
    CustomizationSustainedThrottle,
]
CUSTOMIZATION_WRITES = ["set_customization", "reset_customization"]
CONTEXT_PARAMETER = OpenApiParameter(
    "context",
    str,
    OpenApiParameter.PATH,
    enum=list(CustomizationContext),
    description="The UI surface to customize. Each supported context defines its layout schema and defaults.",
)


class UICustomizationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "user"
    scope_object_read_actions = ["get_customization", "describe_customization"]
    scope_object_write_actions = CUSTOMIZATION_WRITES

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in CUSTOMIZATION_WRITES:
            return [throttle() for throttle in CUSTOMIZATION_THROTTLES]
        return super().get_throttles()

    def _customization_user(self) -> User:
        user = cast(User, self.request.user)
        if not api.is_enabled_for(user, self.team):
            raise NotFound()
        return user

    def initial(self, request: Request, *args, **kwargs) -> None:
        super().initial(request, *args, **kwargs)
        try:
            api.validate_customization_context(self.kwargs["context"])
        except ValueError:
            raise NotFound("Unsupported customization context.") from None

    def get_serializer_context(self) -> dict:
        return {**super().get_serializer_context(), "request": self.request, "view": self}

    @validated_request(
        parameters=[CONTEXT_PARAMETER],
        responses={200: OpenApiResponse(response=CustomizationDescriptionSerializer)},
        operation_id="ui_customization_describe",
        summary="Describe a UI customization context",
        description="Returns the layout validation schema and defaults for a supported context without reading or changing the person's saved layout. Unknown contexts and people without UI customization enabled receive 404.",
    )
    @action(detail=False, methods=["get"], url_path=r"(?P<context>[^/.]+)/schema")
    def describe_customization(self, request: Request, context: str, **kwargs) -> Response:
        self._customization_user()
        return Response(CustomizationDescriptionSerializer(api.describe_customization(context)).data)

    @validated_request(
        parameters=[CONTEXT_PARAMETER],
        responses={200: OpenApiResponse(response=CustomizationSerializer)},
        operation_id="ui_customization_retrieve",
        summary="Get the person's UI customization",
        description="Returns the person's layout for the selected context, or its default. Read it before changing it. Unknown contexts and people without UI customization enabled receive 404.",
    )
    @action(detail=False, methods=["get"], url_path=r"(?P<context>[^/.]+)")
    def get_customization(self, request: Request, context: str, **kwargs) -> Response:
        found = api.get_customization(team=self.team, user=self._customization_user(), context=context)
        return Response(CustomizationSerializer(found).data)

    @validated_request(
        parameters=[CONTEXT_PARAMETER],
        request_serializer=CustomizationRequestSerializer,
        include_serializer_context=True,
        responses={200: OpenApiResponse(response=CustomizationSerializer)},
        operation_id="ui_customization_update",
        summary="Set the person's UI customization",
        description="Replaces the person's layout for the selected context in this project. The context defines its allowed layout schema and limits. Unknown contexts and people without UI customization enabled receive 404.",
    )
    @get_customization.mapping.put
    def set_customization(self, request: Request, context: str, **kwargs) -> Response:
        try:
            saved = api.set_customization(
                team=self.team,
                user=self._customization_user(),
                context=context,
                layout=request.validated_data["layout"],
            )
        except UnavailableTargets as unavailable:
            raise ValidationError({"layout": layout_error_detail(unavailable.problems)}) from None
        return Response(CustomizationSerializer(saved).data)

    @validated_request(
        parameters=[CONTEXT_PARAMETER],
        responses={200: OpenApiResponse(response=CustomizationSerializer)},
        operation_id="ui_customization_destroy",
        summary="Reset the person's UI customization",
        description="Removes the person's saved layout for the selected context and returns its default. Unknown contexts and people without UI customization enabled receive 404.",
    )
    @get_customization.mapping.delete
    def reset_customization(self, request: Request, context: str, **kwargs) -> Response:
        default = api.reset_customization(team=self.team, user=self._customization_user(), context=context)
        return Response(CustomizationSerializer(default).data)
