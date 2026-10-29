from typing import cast
from uuid import UUID

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import (
    DelegatedOAuthAccessTokenAuthentication,
    DelegatedPersonalAPIKeyAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
)
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.models import User

from products.mcp_events.backend.facade import api
from products.mcp_events.backend.facade.contracts import (
    MCPCallbackError,
    MCPEventCredential,
    MCPEventSubscribeInput,
    MCPEventSubscriptionNotFoundError,
)
from products.mcp_events.backend.presentation.serializers import (
    MCPEventArgumentsSerializer,
    MCPEventEmptySerializer,
    MCPEventPreviewSerializer,
    MCPEventSubscribeSerializer,
    MCPEventSubscriptionSerializer,
    MCPEventUnsubscribeSerializer,
)


class MCPEventSubscriptionPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 100


class MCPEventSubscriptionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    pagination_class = MCPEventSubscriptionPagination
    scope_object = "mcp_event_subscription"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["subscribe", "unsubscribe"]
    serializer_class = MCPEventSubscriptionSerializer

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        if not posthoganalytics.feature_enabled(
            "mcp-events",
            cast(User, request.user).distinct_id or str(request.user.pk),
            groups={"organization": str(self.team.organization_id)},
            send_feature_flag_events=False,
        ):
            raise NotFound("MCP event subscriptions are not enabled for this account.")

    def _credential(self, request: Request) -> MCPEventCredential:
        authenticator = request.successful_authenticator
        if isinstance(authenticator, (DelegatedOAuthAccessTokenAuthentication, DelegatedPersonalAPIKeyAuthentication)):
            raise PermissionDenied(
                "Use the original OAuth access token or personal API key directly to manage subscriptions."
            )
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            token = authenticator.access_token
            return MCPEventCredential(principal=f"oauth:{request.user.pk}:{token.application_id}", id=str(token.pk))
        if isinstance(authenticator, PersonalAPIKeyAuthentication):
            key = authenticator.personal_api_key
            return MCPEventCredential(
                principal=f"personal_api_key:{request.user.pk}:{key.pk}",
                id=key.pk,
                last_rolled_at=key.last_rolled_at,
            )
        raise PermissionDenied("Connect using an OAuth token or personal API key to manage subscriptions.")

    @extend_schema(responses=MCPEventSubscriptionSerializer(many=True))
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        paginator = self.paginator
        assert isinstance(paginator, LimitOffsetPagination)
        paginator.request = request
        paginator.limit = paginator.get_limit(request) or MCPEventSubscriptionPagination.default_limit
        paginator.offset = paginator.get_offset(request)
        page = api.list_subscriptions(
            team_id=self.team.pk, user_id=cast(User, request.user).pk, limit=paginator.limit, offset=paginator.offset
        )
        paginator.count = page.count
        return paginator.get_paginated_response(self.get_serializer(page.results, many=True).data)

    @extend_schema(responses=MCPEventSubscriptionSerializer)
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        try:
            subscription = api.get_subscription(
                team_id=self.team.pk, user_id=cast(User, request.user).pk, subscription_id=UUID(str(kwargs["pk"]))
            )
        except (MCPEventSubscriptionNotFoundError, ValueError):
            raise NotFound() from None
        return Response(self.get_serializer(subscription).data)

    @extend_schema(
        operation_id="mcp_event_subscriptions_preview",
        request=MCPEventArgumentsSerializer,
        responses=MCPEventPreviewSerializer,
    )
    @action(detail=False, methods=["POST"], required_scopes=["query:read"])
    def preview(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventArgumentsSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            result = api.preview(
                team_id=self.team.pk, user_id=cast(User, request.user).pk, filters=serializer.validated_data["filters"]
            )
        except ConcurrencyLimitExceeded:
            raise Throttled(detail="Too many queries are running. Try again in a moment.") from None
        return Response(MCPEventPreviewSerializer(result, context=self.get_serializer_context()).data)

    @extend_schema(request=MCPEventSubscribeSerializer, responses=MCPEventSubscriptionSerializer)
    @action(detail=False, methods=["POST"], required_scopes=["mcp_event_subscription:write", "query:read"])
    def subscribe(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventSubscribeSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        credential = self._credential(request)
        try:
            subscription = api.subscribe(
                MCPEventSubscribeInput(
                    team_id=self.team.pk,
                    user_id=cast(User, request.user).pk,
                    credential=credential,
                    filters=data["arguments"]["filters"],
                    url=data["delivery"]["url"],
                    secret=data["delivery"]["secret"],
                    ttl_ms=data["ttl_ms"],
                )
            )
        except MCPCallbackError as error:
            raise ValidationError({"callback": {"reason": error.reason, "detail": str(error)}}) from None
        return Response(self.get_serializer(subscription).data)

    @extend_schema(request=MCPEventUnsubscribeSerializer, responses=MCPEventEmptySerializer)
    @action(detail=False, methods=["POST"], required_scopes=["mcp_event_subscription:write"])
    def unsubscribe(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = MCPEventUnsubscribeSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        principal = self._credential(request).principal
        api.unsubscribe(
            team_id=self.team.pk,
            user_id=cast(User, request.user).pk,
            principal=principal,
            filters=data["arguments"]["filters"],
            url=data["delivery"]["url"],
        )
        return Response(MCPEventEmptySerializer({}).data)
