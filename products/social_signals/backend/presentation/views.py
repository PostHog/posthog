"""
DRF views for social_signals.

Read-only viewsets for mentions and per-team source configuration. The
webhook ingestion endpoint is a standalone view (see :mod:`.webhook`) so it
can be registered outside the project router and stay unauthenticated.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from .serializers import (
    CreateMentionSourceInputSerializer,
    MentionSerializer,
    MentionSourceSerializer,
)

logger = structlog.get_logger(__name__)

SOCIAL_SIGNALS_TAG = "social_signals"


def _parse_filters(request: Request) -> contracts.MentionFilters:
    """Build a MentionFilters DTO from query params. Invalid values raise ParseError."""
    qp = request.query_params

    def _parse_int(name: str, default: int, *, min_value: int = 0, max_value: int | None = None) -> int:
        raw = qp.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ParseError(f"Invalid {name}: {raw!r}") from exc
        if value < min_value:
            raise ParseError(f"{name} must be >= {min_value}")
        if max_value is not None and value > max_value:
            raise ParseError(f"{name} must be <= {max_value}")
        return value

    from datetime import datetime

    def _parse_dt(name: str) -> datetime | None:
        raw = qp.get(name)
        if not raw:
            return None
        text = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ParseError(f"Invalid {name}: {raw!r} (expected ISO-8601)") from exc

    return contracts.MentionFilters(
        platform=qp.get("platform") or None,
        status=qp.get("status") or None,
        search=qp.get("search") or None,
        posted_after=_parse_dt("posted_after"),
        posted_before=_parse_dt("posted_before"),
        limit=_parse_int("limit", 100, min_value=1, max_value=500),
        offset=_parse_int("offset", 0),
    )


@extend_schema(tags=[SOCIAL_SIGNALS_TAG])
class MentionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read-only access to ingested social mentions for a team."""

    scope_object = "social_signals"
    scope_object_read_actions = ["list", "retrieve"]

    @extend_schema(
        parameters=[
            OpenApiParameter("platform", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("status", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("posted_after", OpenApiTypes.DATETIME, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("posted_before", OpenApiTypes.DATETIME, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: MentionSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List ingested mentions for the team."""
        filters = _parse_filters(request)
        mentions = api.list_mentions(team_id=self.team_id, filters=filters)
        return Response(MentionSerializer(instance=mentions, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses={200: MentionSerializer},
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Fetch a single mention with its analyses."""
        try:
            mention = api.get_mention(team_id=self.team_id, mention_id=UUID(pk))
        except api.MentionNotFoundError:
            return Response({"detail": "Mention not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"detail": "Invalid mention id"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MentionSerializer(instance=mention).data)


@extend_schema(tags=[SOCIAL_SIGNALS_TAG])
class MentionSourceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-team ingestion endpoint configuration (webhook tokens, etc.)."""

    scope_object = "social_signals"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "rotate_token"]

    @extend_schema(responses={200: MentionSourceSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        sources = api.list_sources(self.team_id)
        return Response(MentionSourceSerializer(instance=sources, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses={200: MentionSourceSerializer},
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            source = api.get_source(team_id=self.team_id, source_id=UUID(pk))
        except api.MentionSourceNotFoundError:
            return Response({"detail": "Source not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"detail": "Invalid source id"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MentionSourceSerializer(instance=source).data)

    @validated_request(
        request_serializer=CreateMentionSourceInputSerializer,
        responses={201: OpenApiResponse(response=MentionSourceSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Get-or-create the source for the given kind. Idempotent per (team, kind)."""
        kind = request.validated_data["kind"]
        source = api.get_or_create_source(team_id=self.team_id, kind=kind)
        return Response(MentionSourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        request=None,
        responses={200: MentionSourceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="rotate_token")
    def rotate_token(self, request: Request, pk: str, **kwargs: Any) -> Response:
        """Rotate the ingest_token for a source. Old token stops working immediately."""
        try:
            source = api.rotate_source_token(team_id=self.team_id, source_id=UUID(pk))
        except api.MentionSourceNotFoundError:
            return Response({"detail": "Source not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"detail": "Invalid source id"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MentionSourceSerializer(instance=source).data)


def _parse_webhook_body(request: Request) -> dict:
    """Parse the JSON body from a webhook POST. Accepts top-level dict or list."""
    try:
        body = request.body or b"{}"
        payload = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("social_signals.webhook.invalid_body", error=str(exc))
        raise ParseError("Invalid JSON body") from exc
    if isinstance(payload, list):
        return {"mentions": payload}
    if not isinstance(payload, dict):
        raise ParseError("Body must be a JSON object or array")
    return payload
