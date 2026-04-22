from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class LegalDocument(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class DocumentType(models.TextChoices):
        BAA = "BAA", "Business Associate Agreement"
        DPA = "DPA", "Data Processing Agreement"

    class Status(models.TextChoices):
        SUBMITTED_FOR_SIGNATURE = "submitted_for_signature", "Submitted for signature"
        SIGNED = "signed", "Signed"

    activity_logging_on_delete = True

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="legal_documents",
    )
    document_type = models.CharField(max_length=8, choices=DocumentType.choices)
    company_name = models.CharField(max_length=255)
    company_address = models.CharField(max_length=512)
    representative_email = models.EmailField()

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.SUBMITTED_FOR_SIGNATURE,
    )
    # Pre-signed download URL for the signed PDF, populated by PandaDoc's webhook
    # once the customer counter-signs the envelope.
    signed_document_url = models.URLField(blank=True, max_length=2048)

    # PandaDoc document uuid. Empty until the create call succeeds. Used as the
    # join key for inbound PandaDoc webhooks.
    pandadoc_document_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        # An org has at most one BAA and at most one DPA. If they need a new one (e.g.,
        # the company renamed), a staff member deletes the old row from Django admin.
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_type"],
                name="unique_legal_document_per_org_and_type",
            ),
        ]
