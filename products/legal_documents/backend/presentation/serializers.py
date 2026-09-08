from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.models.organization import Organization

from ..facade import api
from ..facade.contracts import LegalDocumentDTO
from ..facade.enums import BaaBlockReason, DocumentType


class LegalDocumentSerializer(DataclassSerializer):
    """Output serializer — what the API returns for every row."""

    class Meta:
        dataclass = LegalDocumentDTO


BAA_BLOCK_MESSAGES: dict[BaaBlockReason, str] = {
    BaaBlockReason.STARTUP_PROGRAM: "BAAs aren't covered by startup program credits. Contact us to discuss options.",
    BaaBlockReason.NO_QUALIFYING_ADDON: "A Boost, Scale, or Enterprise add-on is required to generate a BAA.",
}


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
        help_text="The customer legal entity entering the agreement (PandaDoc's Client.Company).",
    )
    company_address = serializers.CharField(
        max_length=512,
        help_text="The customer address (PandaDoc's Client.StreetAddress).",
    )
    representative_email = serializers.EmailField(
        help_text="Email the signed PandaDoc envelope is sent to (PandaDoc's Client.Email).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        document_type = attrs["document_type"]
        organization: Organization = self.context["view"].organization

        if document_type == DocumentType.BAA:
            # The override flag is evaluated for the same person posthog-js uses in the app.
            user = self.context["request"].user
            distinct_id = str(user.distinct_id or organization.id)
            block_reason = api.get_baa_block_reason(organization, distinct_id)
            if block_reason is not None:
                raise PermissionDenied(
                    BAA_BLOCK_MESSAGES.get(block_reason, BAA_BLOCK_MESSAGES[BaaBlockReason.NO_QUALIFYING_ADDON])
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
