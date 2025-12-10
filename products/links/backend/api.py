from typing import Any

from django.db import transaction
from django.db.models import QuerySet

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.validators import UniqueTogetherValidator

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.link import Link
from posthog.models.team.team import Team

from products.links.backend.utils import get_hog_function

logger = structlog.get_logger(__name__)


class LinkSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    short_code = serializers.CharField(required=True, allow_null=False)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Link
        fields = [
            "id",
            "redirect_url",
            "short_link_domain",
            "short_code",
            "description",
            "expires_at",
            "created_at",
            "updated_at",
            "created_by",
            "hog_function_id",
            "_create_in_folder",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        validators = [
            UniqueTogetherValidator(
                queryset=Link.objects.all(),
                fields=["short_link_domain", "short_code"],
                message="A link with this short code already exists for this domain",
            )
        ]

    def create(self, validated_data: dict[str, Any]) -> Link:
        team = Team.objects.get(id=self.context["team_id"])

        if validated_data.get("short_link_domain") != "phog.gg":
            raise serializers.ValidationError({"short_link_domain": "Only phog.gg is allowed as a short link domain"})

        redirect_url = validated_data.get("redirect_url")
        if not redirect_url:
            raise serializers.ValidationError({"redirect_url": "Redirect URL is required"})

        with transaction.atomic():
            hog_function = get_hog_function(team=team, redirect_url=redirect_url)
            hog_function.created_by = self.context["request"].user
            hog_function.save()

            link = Link.objects.create(
                team=team,
                created_by=self.context["request"].user,
                hog_function=hog_function,
                **validated_data,
            )

        logger.info("link_created", id=link.id, team_id=team.id)
        return link


class LinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and delete links.
    """

    scope_object = "link"
    queryset = Link.objects.all()
    serializer_class = LinkSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    # Use the team from the user's current context when not in a team-specific route
    param_derived_from_user_current_team = "team_id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    # TODO: Call the /invalidate route on the Rust service
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().update(request, *args, **kwargs)

    # TODO: Call the /invalidate route on the Rust service
    # and wait for confirmation before we delete this link
    #
    # TODO: Consider implementing "archiving" rather than deletion
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        logger.info("link_deleted", id=instance.id, team_id=self.team_id)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="check-availability")
    def check_availability(self, request: Request, **kwargs: Any) -> Response:
        """
        Check if a short_link_domain and short_code combination is available.
        Query params:
            - short_link_domain: The domain to check (required)
            - short_code: The short code to check (required)
        Returns:
            - available: boolean indicating if the combination is available
        """
        short_link_domain = request.query_params.get("short_link_domain")
        if not short_link_domain:
            raise serializers.ValidationError({"short_link_domain": "Short link domain is required"})
        short_code = request.query_params.get("short_code")
        if not short_code:
            raise serializers.ValidationError({"short_code": "Short code is required"})

        exists = Link.objects.filter(short_link_domain=short_link_domain, short_code=short_code).exists()
        return Response({"available": not exists}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="generate-short-code")
    def generate_short_code(self, request: Request, **kwargs: Any) -> Response:
        """
        Generate an AI-powered short code suggestion based on redirect URL.

        Request body:
            - redirect_url: The destination URL (required)

        Returns:
            - short_code: suggested short code
            - success: boolean
            - error: error message if failed (optional)
        """
        redirect_url = request.data.get("redirect_url")

        if not redirect_url:
            raise serializers.ValidationError({"redirect_url": "Redirect URL is required"})

        try:
            from products.links.backend.services.short_code_generator import generate_short_code

            short_code = generate_short_code(redirect_url)
            return Response({"short_code": short_code, "success": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception(f"Failed to generate short code: {e}")
            return Response(
                {"short_code": None, "success": False, "error": "Failed to generate short code"},
                status=status.HTTP_200_OK,
            )
