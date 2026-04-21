from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from posthog.cloud_utils import get_cached_instance_license
from posthog.models.organization import Organization

from ee.billing.billing_manager import BillingManager

from ..models import LegalDocument

BAA_ADDON_TYPES = {"boost", "scale", "enterprise"}
DPA_SUBMITTABLE_MODES = {LegalDocument.DPAMode.PRETTY, LegalDocument.DPAMode.LAWYER}


def _has_qualifying_baa_addon(organization: Organization) -> bool:
    billing = BillingManager(get_cached_instance_license()).get_billing(organization)
    for product in billing.get("products") or []:
        for addon in product.get("addons") or []:
            if addon.get("type") in BAA_ADDON_TYPES and addon.get("subscribed"):
                return True
    return False


class LegalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalDocument
        fields = (
            "id",
            "document_type",
            "company_name",
            "company_address",
            "representative_name",
            "representative_title",
            "representative_email",
            "dpa_mode",
            "status",
            "signed_document_url",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "signed_document_url",
            "created_by",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "document_type": {"help_text": "Either 'BAA' or 'DPA'."},
            "company_name": {"help_text": "The customer legal entity entering the agreement."},
            "company_address": {
                "help_text": "Customer address. Required for DPAs; ignored for BAAs.",
                "required": False,
                "allow_blank": True,
            },
            "representative_name": {"help_text": "Name of the signer at the customer."},
            "representative_title": {"help_text": "Title of the signer at the customer."},
            "representative_email": {"help_text": "Email the signed PandaDoc envelope is sent to."},
            "dpa_mode": {
                "help_text": (
                    "DPA style: 'pretty' or 'lawyer' for submittable versions. "
                    "'fairytale' and 'tswift' are preview-only on posthog.com and are not accepted by the API."
                ),
                "required": False,
                "allow_blank": True,
            },
            "status": {
                "help_text": "Lifecycle: 'submitted_for_signature' until the PandaDoc signed-URL webhook flips it to 'signed'.",
            },
            "signed_document_url": {
                "help_text": "Download URL for the fully-signed PDF. Populated by PandaDoc via the public webhook.",
            },
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        document_type = attrs.get("document_type")
        organization: Organization = self.context["view"].organization

        if document_type == LegalDocument.DocumentType.BAA:
            if not _has_qualifying_baa_addon(organization):
                raise PermissionDenied("A Boost, Scale, or Enterprise add-on is required to generate a BAA.")
            attrs["dpa_mode"] = ""
            attrs["company_address"] = ""
        elif document_type == LegalDocument.DocumentType.DPA:
            if not attrs.get("company_address"):
                raise serializers.ValidationError({"company_address": "Company address is required for a DPA."})
            dpa_mode = attrs.get("dpa_mode")
            if dpa_mode not in DPA_SUBMITTABLE_MODES:
                raise serializers.ValidationError(
                    {"dpa_mode": ("Pick 'pretty' or 'lawyer' to submit. 'fairytale' and 'tswift' are preview-only.")}
                )

        # Only one BAA and one DPA per organization. If they need a new one, a staff
        # member deletes the old row from Django admin. The DB-level unique constraint
        # (unique_legal_document_per_org_and_type) is the source of truth — we catch
        # it here so we can return a 400 with a clear message instead of a 500.
        if (
            document_type
            and LegalDocument.objects.filter(organization=organization, document_type=document_type).exists()
        ):
            raise serializers.ValidationError(
                {
                    "document_type": (
                        f"Your organization already has a {document_type}. Contact support if you need a new one."
                    )
                }
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> LegalDocument:
        validated_data["organization"] = self.context["view"].organization
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
