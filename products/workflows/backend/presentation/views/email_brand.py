import re
from typing import Any

from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models import UploadedMedia
from posthog.models.integration import Integration
from posthog.models.uploaded_media import MEDIA_PURPOSE_EMAIL

from products.messaging.backend.api.message_templates import UnlayerDesignField
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.unlayer import UnlayerError, render_design_html
from products.workflows.backend.models.email_brand import EmailBrand
from products.workflows.backend.presentation.views.email_brand_detection import (
    EmailBrandDetectionSerializer,
    EmailBrandDetectRequestSerializer,
    GitHubBusyError,
    RepositoryUnreadableError,
)
from products.workflows.backend.presentation.views.feature_gates import require_team_feature_flag
from products.workflows.backend.services.brand_detection.detector import UnknownAppRoot
from products.workflows.backend.services.email_brand_detection import (
    GitHubBusy,
    RepositoryUnreadable,
    detect_repository_brand,
)
from products.workflows.backend.services.email_brand_starter_template import StarterTemplate, build_starter_template

BRAND_DETECTION_FEATURE_FLAG = "workflows-brand-detection"

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class HexColorField(serializers.CharField):
    default_error_messages = {"invalid_hex_color": "Enter a color as #rrggbb, for example #1d4aff."}

    def to_internal_value(self, data: Any) -> str:
        value = super().to_internal_value(data)
        if not HEX_COLOR.match(value):
            self.fail("invalid_hex_color")
        return value.lower()


class EmailBrandSourceSerializer(serializers.Serializer):
    path = serializers.CharField(max_length=1000, help_text="Repository path of the file the value was read from.")
    line = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, help_text="1-based line in that file, when known."
    )
    detected_value = serializers.CharField(
        max_length=1000,
        allow_blank=True,
        help_text="The value detection proposed. The field reports edited while its value differs from this. "
        "For the logo it is the id of the imported media.",
    )


class EmailBrandEditedSerializer(serializers.Serializer):
    name = serializers.BooleanField(help_text="Whether the name differs from its detected value.")
    logo = serializers.BooleanField(help_text="Whether the logo differs from its detected value.")
    primary_color = serializers.BooleanField(help_text="Whether the primary color differs from its detected value.")
    accent_color = serializers.BooleanField(help_text="Whether the accent color differs from its detected value.")
    text_color = serializers.BooleanField(help_text="Whether the text color differs from its detected value.")
    background_color = serializers.BooleanField(
        help_text="Whether the background color differs from its detected value."
    )
    font_family = serializers.BooleanField(help_text="Whether the font family differs from its detected value.")


class EmailBrandSerializer(serializers.ModelSerializer):
    logo = TeamScopedPrimaryKeyRelatedField(
        queryset=UploadedMedia.objects.filter(purpose=MEDIA_PURPOSE_EMAIL, pending=False),
        required=False,
        allow_null=True,
        help_text="Id of an image in this project's email media library to show in the email header. "
        "Null shows the name instead.",
    )
    logo_url = serializers.SerializerMethodField(help_text="Public URL of the logo image, or null without a logo.")
    primary_color = HexColorField(required=False, help_text="Main brand color as #rrggbb, used for buttons.")
    accent_color = HexColorField(required=False, help_text="Secondary brand color as #rrggbb, used for highlights.")
    text_color = HexColorField(required=False, help_text="Body text color as #rrggbb.")
    background_color = HexColorField(required=False, help_text="Email background color as #rrggbb.")
    sources = serializers.DictField(
        child=EmailBrandSourceSerializer(),
        required=False,
        help_text="Where each detected value came from, keyed by field name. A field without an entry was entered "
        f"by hand. Keys: {', '.join(EmailBrand.SOURCED_FIELDS)}.",
    )
    edited = serializers.SerializerMethodField(
        help_text="Per value, whether it differs from the value detection found. A value without a source is never edited."
    )

    class Meta:
        model = EmailBrand
        fields = [
            "id",
            "name",
            "logo",
            "logo_url",
            "primary_color",
            "accent_color",
            "text_color",
            "background_color",
            "font_family",
            "font_stack",
            "source_repository",
            "app_root",
            "sources",
            "edited",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "logo_url", "edited", "created_at", "updated_at"]
        extra_kwargs = {
            "id": {"help_text": "Unique id of the Email brand."},
            "created_at": {"help_text": "When the Email brand was first saved."},
            "updated_at": {"help_text": "When the Email brand last changed."},
            "name": {"help_text": "Brand name. Shown in the email header when there is no logo."},
            "font_family": {"help_text": "Font family name, for example Inter."},
            "font_stack": {
                "help_text": "CSS font-family stack used in emails. It ends in fonts every email client has, "
                "for example 'Inter, Arial, Helvetica, sans-serif'."
            },
            "source_repository": {
                "help_text": "Full name (owner/repo) of the GitHub repository the brand was detected from. "
                "Empty when entered by hand."
            },
            "app_root": {"help_text": "Directory inside the repository that holds the app detection read."},
        }

    def get_logo_url(self, brand: EmailBrand) -> str | None:
        return brand.logo.get_absolute_url() if brand.logo else None

    @extend_schema_field(EmailBrandEditedSerializer)
    def get_edited(self, brand: EmailBrand) -> dict[str, bool]:
        return brand.edited_fields()

    def validate_sources(self, sources: dict[str, dict]) -> dict[str, dict]:
        unknown = sorted(set(sources) - set(EmailBrand.SOURCED_FIELDS))
        if unknown:
            raise serializers.ValidationError(f"Unknown fields: {', '.join(unknown)}.")
        return {
            field: self._normalized_source(field, self._complete_source(field, source))
            for field, source in sources.items()
        }

    def _complete_source(self, field: str, source: dict) -> dict:
        # A partial PATCH makes DRF skip missing required fields in nested serializers too, so a source
        # record without its path would save and then break every read. Validate each record whole.
        record = EmailBrandSourceSerializer(data=source)
        if not record.is_valid():
            raise serializers.ValidationError({field: record.errors})
        return record.validated_data

    def _normalized_source(self, field: str, source: dict) -> dict:
        if field in EmailBrand.COLOR_FIELDS:
            return {**source, "detected_value": source["detected_value"].lower()}
        return source


class EmailBrandStarterDesignSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Suggested name for the starter template.")
    description = serializers.CharField(help_text="Description the starter template is saved with.")
    subject = serializers.CharField(help_text="Suggested email subject line.")
    design = UnlayerDesignField(
        help_text="Email editor design built from the Email brand: logo header, heading, body, button and "
        "unsubscribe footer."
    )


class EmailBrandStarterTemplateSerializer(serializers.Serializer):
    template_id = serializers.UUIDField(help_text="Id of the email template created from the Email brand.")


class DesignRenderingUnavailable(exceptions.APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "design_rendering_unavailable"
    default_detail = "This instance can't render email designs. Open the starter design in the email editor instead."


class EmailBrandViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["current", "starter_design"]
    scope_object_write_actions = ["update_current", "detect", "create_starter_template"]
    # The brand styles every workflow in the project, so access to one workflow must not reach it.
    requires_resource_level_access = True
    queryset = EmailBrand.objects.unscoped()
    serializer_class = EmailBrandSerializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_team_feature_flag(BRAND_DETECTION_FEATURE_FLAG, self.team.parent_team or self.team)

    @extend_schema(
        summary="Get the project's Email brand",
        responses={
            200: EmailBrandSerializer,
            404: OpenApiResponse(description="The project has no Email brand yet."),
        },
    )
    @action(detail=False, methods=["GET"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        return Response(self.get_serializer(self._saved_brand()).data)

    @extend_schema(
        summary="Create or update the project's Email brand",
        description="Only the provided fields change. The first call creates the Email brand with defaults "
        "for every field it leaves out.",
        request=EmailBrandSerializer,
        responses={200: EmailBrandSerializer},
    )
    @current.mapping.patch
    def update_current(self, request: Request, **kwargs: Any) -> Response:
        with transaction.atomic():
            # Lock the row because save() writes every column: two PATCHes of different fields would otherwise
            # each restore the other's stale value.
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
        request_serializer=EmailBrandDetectRequestSerializer,
        responses={
            200: OpenApiResponse(response=EmailBrandDetectionSerializer),
            400: OpenApiResponse(description="Invalid input, or the GitHub App cannot read the repository."),
            429: OpenApiResponse(description="GitHub is busy. Try again in a minute."),
        },
        summary="Detect an Email brand from a GitHub repository",
        description="Reads the repository's brand files and proposes an Email brand with the source of each value. "
        "Does not save the Email brand. A detection is reused for 10 minutes unless refresh is set.",
    )
    @action(detail=False, methods=["POST"])
    def detect(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            detection = detect_repository_brand(
                team_id=self._project_team_id(),
                integration=self._github_integration(data["integration_id"]),
                repository=data["repository"],
                app_root=data.get("app_root"),
                refresh=data["refresh"],
            )
        except GitHubBusy:
            raise GitHubBusyError()
        except RepositoryUnreadable:
            raise RepositoryUnreadableError()
        except UnknownAppRoot as error:
            raise exceptions.ValidationError({"app_root": str(error)})
        return Response(EmailBrandDetectionSerializer(detection).data)

    def _github_integration(self, integration_id: int) -> Integration:
        integration = Integration.objects.filter(team_id=self.team.id, kind="github", id=integration_id).first()
        if integration is None:
            raise exceptions.ValidationError({"integration_id": "No GitHub integration with this id in this project."})
        return integration

    @extend_schema(
        summary="Build a starter email design from the Email brand",
        description="Returns the design without saving anything, so the email editor can open it preloaded.",
        responses={
            200: EmailBrandStarterDesignSerializer,
            404: OpenApiResponse(description="The project has no Email brand yet."),
        },
    )
    @action(detail=False, methods=["GET"])
    def starter_design(self, request: Request, **kwargs: Any) -> Response:
        starter = build_starter_template(self._saved_brand())
        return Response(EmailBrandStarterDesignSerializer(starter).data)

    @extend_schema(
        summary="Create a starter email template from the Email brand",
        description="Creates an ordinary email template. Later Email brand changes do not change it. "
        "Returns 422 with the code design_rendering_unavailable when this instance cannot render designs; "
        "open the starter design in the email editor instead.",
        request=None,
        responses={
            201: EmailBrandStarterTemplateSerializer,
            404: OpenApiResponse(description="The project has no Email brand yet."),
            422: OpenApiResponse(description="Design rendering is unavailable on this instance."),
        },
    )
    @action(detail=False, methods=["POST"])
    def create_starter_template(self, request: Request, **kwargs: Any) -> Response:
        starter = build_starter_template(self._saved_brand())
        template = self._create_template(starter, html=self._render(starter))
        return Response(
            EmailBrandStarterTemplateSerializer({"template_id": template.id}).data, status=status.HTTP_201_CREATED
        )

    def _render(self, starter: StarterTemplate) -> str:
        try:
            return render_design_html(starter.design)
        except UnlayerError as error:
            # Any render failure falls back to the email editor, which exports the same design in the browser
            # and needs no key.
            raise DesignRenderingUnavailable() from error

    def _create_template(self, starter: StarterTemplate, html: str) -> MessageTemplate:
        return MessageTemplate.objects.create(
            team_id=self.team.id,
            created_by=self.request.user,
            name=starter.name,
            description=starter.description,
            type="email",
            content={
                "templating": "liquid",
                "email": {"subject": starter.subject, "html": html, "design": starter.design},
            },
        )

    def _saved_brand(self) -> EmailBrand:
        brand = self._project_brands().first()
        if brand is None:
            raise exceptions.NotFound("This project has no Email brand yet.")
        return brand

    def _project_brands(self):
        return EmailBrand.objects.for_team(self._project_team_id(), canonical=True)

    def _project_team_id(self) -> int:
        return self.team.parent_team_id or self.team.id
