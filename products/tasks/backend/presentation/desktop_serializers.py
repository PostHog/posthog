from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.tasks.backend.facade.contracts import DesktopBetaTermsAcceptanceDTO


@extend_schema_serializer(many=False)
class DesktopBetaTermsAcceptanceSerializer(DataclassSerializer):
    is_desktop_beta_terms_accepted = serializers.BooleanField(
        read_only=True,
        help_text="Whether the organization has accepted the PostHog Desktop beta terms.",
    )

    class Meta:
        dataclass = DesktopBetaTermsAcceptanceDTO
