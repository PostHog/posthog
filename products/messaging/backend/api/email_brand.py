import re
import dataclasses
from typing import Any, cast
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.integration import Integration

from products.messaging.backend.api.branded_starter_flag import require_branded_starter
from products.messaging.backend.api.github_brand import (
    GITHUB_BUSY,
    GitHubBrandErrorSerializer,
    GitHubBrandRequestSerializer,
    GitHubBrandSerializer,
)
from products.messaging.backend.models import EmailBrand
from products.messaging.backend.services.github_brand import GitHubBusy, RepositoryUnreadable, detect_repository_brand

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class HexColorField(serializers.CharField):
    default_error_messages = {"invalid_hex_color": "Enter a six-digit hex color, like #1d4aff."}

    def to_internal_value(self, data: Any) -> str:
        value = super().to_internal_value(data)
        if not HEX_COLOR.match(value):
            self.fail("invalid_hex_color")
        return value.lower()


class HttpUrlField(serializers.CharField):
    default_error_messages = {"invalid_http_url": "Enter an http or https URL."}

    def to_internal_value(self, data: Any) -> str:
        value = super().to_internal_value(data)
        if not _is_http_url_with_host(value):
            self.fail("invalid_http_url")
        return value


def _is_http_url_with_host(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


class EmailBrandSerializer(serializers.ModelSerializer):
    primary_color = HexColorField(
        required=False, help_text="Main brand color as a six-digit hex color, like #1d4aff. Used for buttons."
    )
    logo_url = HttpUrlField(
        max_length=2048,
        required=False,
        allow_null=True,
        help_text="Public http(s) URL of the logo shown in the email header. Null shows the brand name instead.",
    )

    class Meta:
        model = EmailBrand
        fields = ["id", "name", "primary_color", "logo_url", "source", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "id": {"help_text": "Unique id of the Email brand."},
            "name": {"help_text": "Brand name, shown in the email header and footer."},
            "source": {
                "help_text": "How the brand was filled in before it was saved: detected from the team's website, "
                "detected from a GitHub repository, or entered by hand.",
            },
            "created_at": {"help_text": "When the Email brand was first saved."},
            "updated_at": {"help_text": "When the Email brand last changed."},
        }


class EmailBrandViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["current"]
    scope_object_write_actions = ["update_current", "detect_from_github"]
    # The brand styles every email in the project, so access to one workflow must not reach it.
    requires_resource_level_access = True
    queryset = EmailBrand.objects.unscoped()
    serializer_class = EmailBrandSerializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_branded_starter(cast(User, request.user), self.team)

    @extend_schema(
        summary="Get the project's Email brand",
        responses={
            200: EmailBrandSerializer,
            404: OpenApiResponse(description="The project has no saved Email brand yet."),
        },
    )
    @action(detail=False, methods=["GET"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        brand = self._project_brands().first()
        if brand is None:
            raise exceptions.NotFound("This project has no saved Email brand yet.")
        return Response(self.get_serializer(brand).data)

    @extend_schema(
        summary="Save the project's Email brand",
        description="Only the provided fields change. The first save creates the Email brand with defaults "
        "for every field it leaves out.",
        request=EmailBrandSerializer,
        responses={200: EmailBrandSerializer},
    )
    @current.mapping.patch
    def update_current(self, request: Request, **kwargs: Any) -> Response:
        with transaction.atomic():
            # save() writes every column, so without the lock two saves of different fields could each
            # restore the other's stale value.
            brand, _ = (
                self._project_brands()
                .select_for_update()
                .get_or_create(team_id=self._project_team_id(), defaults={"created_by": request.user})
            )
            serializer = self.get_serializer(brand, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(serializer.data)

    @validated_request(
        request_serializer=GitHubBrandRequestSerializer,
        responses={
            200: OpenApiResponse(response=GitHubBrandSerializer),
            400: OpenApiResponse(
                response=GitHubBrandErrorSerializer,
                description="Invalid input, or a repository the GitHub App cannot read.",
            ),
            429: OpenApiResponse(response=GitHubBrandErrorSerializer, description=GITHUB_BUSY),
        },
        summary="Detect the Email brand from a GitHub repository",
        description="Reads the repository's name, primary color and raster logo, and stores the logo. "
        "Does not save the Email brand.",
    )
    @action(detail=False, methods=["POST"])
    def detect_from_github(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        integration = self._github_integration(request.validated_data["integration_id"])
        try:
            brand = detect_repository_brand(
                self.team, cast(User, request.user), integration, request.validated_data["repository"]
            )
        except RepositoryUnreadable as error:
            raise exceptions.ValidationError({"repository": "The GitHub App cannot read this repository."}) from error
        except GitHubBusy as error:
            raise exceptions.Throttled(detail=GITHUB_BUSY) from error
        return Response(GitHubBrandSerializer(dataclasses.asdict(brand)).data)

    def _github_integration(self, integration_id: int) -> Integration:
        integration = Integration.objects.filter(team_id=self.team.id, kind="github", id=integration_id).first()
        if integration is None:
            raise exceptions.ValidationError({"integration_id": "Choose a GitHub integration in this environment."})
        return integration

    def _project_brands(self) -> QuerySet[EmailBrand]:
        return EmailBrand.objects.for_team(self._project_team_id(), canonical=True)

    def _project_team_id(self) -> int:
        return self.team.parent_team_id or self.team.id
