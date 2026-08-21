from typing import Any

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import WebhookSignatureAuthentication

from products.tasks.backend.facade.billing import (
    TASK_USAGE_SIGNATURE_HEADER,
    TASK_USAGE_TIMESTAMP_HEADER,
    get_local_task_token_cost,
)
from products.tasks.backend.presentation.serializers import (
    InternalTaskUsageRequestSerializer,
    InternalTaskUsageResponseSerializer,
)


class TaskUsageCrossRegionAuthentication(WebhookSignatureAuthentication):
    def get_signature_header(self) -> str:
        return TASK_USAGE_SIGNATURE_HEADER

    def get_timestamp_header(self) -> str:
        return TASK_USAGE_TIMESTAMP_HEADER

    def build_hmac_input(self, timestamp: str, body: str) -> str:
        return f"v0:{timestamp}:{body}"

    def get_signing_secret(self, request: Request) -> str | None:
        return settings.PERSONAL_SPEND_CROSS_REGION_SECRET or None

    def authenticate(self, request: Request) -> tuple[AnonymousUser, Any] | None:
        try:
            return super().authenticate(request)
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed("Invalid request body encoding.")


class InternalTaskUsageViewSet(viewsets.ViewSet):
    authentication_classes = [TaskUsageCrossRegionAuthentication]
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    @extend_schema(exclude=True)
    def create(self, request: Request) -> Response:
        serializer = InternalTaskUsageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_cost = get_local_task_token_cost(**serializer.validated_data)
        return Response(
            InternalTaskUsageResponseSerializer({"token_cost_usd": token_cost}).data,
            status=status.HTTP_200_OK,
        )
