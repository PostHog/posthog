from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.models.organization import Organization

from ..facade import api
from ..facade.contracts import LegalDocumentDTO
from ..facade.enums import DPA_SUBMITTABLE_MODES, DocumentType


class LegalDocumentSerializer(DataclassSerializer):
    """Output serializer — what the API returns for every row."""

    class Meta:
        dataclass = LegalDocumentDTO


class CreateLegalDocumentSerializer(serializers.Serializer):
    """
    Input serializer for POST. Mirrors the submittable fields on the model plus
    cross-field rules (BAA addon, DPA mode, uniqueness). The view supplies the
    organization and submitting user.
    """

    document_type = serializers.ChoiceField(
        choices=[(DocumentType.BAA.value, "BAA"), (DocumentType.DPA.value, "DPA")],
        help_text="Either 'BAA' or 'DPA'.",
    )
    company_name = serializers.CharField(
        max_length=255,
        help_text="The customer legal entity entering the agreement.",
    )
    company_address = serializers.CharField(
        max_length=512,
        required=False,
        allow_blank=True,
        default="",
        help_text="Customer address. Required for DPAs; ignored for BAAs.",
    )
    representative_name = serializers.CharField(
        max_length=255,
        help_text="Name of the signer at the customer.",
    )
    representative_title = serializers.CharField(
        max_length=255,
        help_text="Title of the signer at the customer.",
    )
    representative_email = serializers.EmailField(
        help_text="Email the signed PandaDoc envelope is sent to.",
    )
    dpa_mode = serializers.CharField(
        max_length=16,
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "DPA style: 'pretty' or 'lawyer' for submittable versions. "
            "'fairytale' and 'tswift' are preview-only on posthog.com and are not accepted by the API."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        document_type = attrs["document_type"]
        organization: Organization = self.context["view"].organization

        if document_type == DocumentType.BAA:
            if not api.has_qualifying_baa_addon(organization):
                raise PermissionDenied("A Boost, Scale, or Enterprise add-on is required to generate a BAA.")
            attrs["dpa_mode"] = ""
            attrs["company_address"] = ""
        elif document_type == DocumentType.DPA:
            if not attrs.get("company_address"):
                raise serializers.ValidationError({"company_address": "Company address is required for a DPA."})
            if attrs.get("dpa_mode") not in DPA_SUBMITTABLE_MODES:
                raise serializers.ValidationError(
                    {"dpa_mode": ("Pick 'pretty' or 'lawyer' to submit. 'fairytale' and 'tswift' are preview-only.")}
                )

        # Only one BAA and one DPA per organization. If they need a new one, a staff
        # member deletes the old row from Django admin. The DB-level unique constraint
        # (unique_legal_document_per_org_and_type) is the source of truth — we catch
        # it here so we can return a 400 with a clear message instead of a 500.
        if api.exists_for_organization_and_type(organization.id, document_type):
            raise serializers.ValidationError(
                {
                    "document_type": (
                        f"Your organization already has a {document_type}. Contact support if you need a new one."
                    )
                }
            )

        return attrs


class LegalDocumentSignedWebhookSerializer(serializers.Serializer):
    secret = serializers.CharField(write_only=True, max_length=128)
    signed_document_url = serializers.URLField(max_length=2048)

    def validate_signed_document_url(self, value: str) -> str:
        if not value.lower().startswith(("http://", "https://")):
            raise serializers.ValidationError("Must be an absolute URL.")
        return value
