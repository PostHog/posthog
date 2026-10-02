import re
from typing import Any

from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models import UploadedMedia
from posthog.models.uploaded_media import MEDIA_PURPOSE_EMAIL

from products.workflows.backend.models.email_brand import EmailBrand
from products.workflows.backend.presentation.views.feature_gates import require_team_feature_flag

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
        return {field: self._normalized_source(field, source) for field, source in sources.items()}

    def _normalized_source(self, field: str, source: dict) -> dict:
        if field in EmailBrand.COLOR_FIELDS:
            return {**source, "detected_value": source["detected_value"].lower()}
        return source


class EmailBrandViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["current"]
    scope_object_write_actions = ["update_current"]
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
        brand = self._project_brands().first()
        if brand is None:
            raise exceptions.NotFound("This project has no Email brand yet.")
        return Response(self.get_serializer(brand).data)

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

    def _project_brands(self):
        return EmailBrand.objects.for_team(self._project_team_id(), canonical=True)

    def _project_team_id(self) -> int:
        return self.team.parent_team_id or self.team.id
