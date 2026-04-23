import secrets

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


def _generate_webhook_secret() -> str:
    # 32 bytes of entropy encoded URL-safely — matches PandaDoc/Zapier webhook-token style length.
    return secrets.token_urlsafe(32)


class LegalDocument(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class DocumentType(models.TextChoices):
        BAA = "BAA", "Business Associate Agreement"
        DPA = "DPA", "Data Processing Agreement"

    class DPAMode(models.TextChoices):
        PRETTY = "pretty", "A perfectly legal doc, but with some pizazz"
        LAWYER = "lawyer", "Drab and dull — preferred by lawyers"
        FAIRYTALE = "fairytale", "A fairy tale story"
        TSWIFT = "tswift", "Taylor Swift's version"

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
    company_address = models.CharField(max_length=512, blank=True)
    representative_name = models.CharField(max_length=255)
    representative_title = models.CharField(max_length=255)
    representative_email = models.EmailField()
    # Only meaningful for DPAs. fairytale/tswift are preview-only in the UI; the
    # serializer rejects them on submit. But we persist the mode for analytics and future-proofing.
    dpa_mode = models.CharField(max_length=16, blank=True, choices=DPAMode.choices)

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.SUBMITTED_FOR_SIGNATURE,
    )
    # Pre-signed download URL for the signed PDF, populated by PandaDoc via Zapier
    # callback once the customer signs.
    signed_document_url = models.URLField(blank=True, max_length=2048)
    # Pre-shared secret we send along with the PostHog event for Zapier → PandaDoc,
    # and then verify on the public webhook when the signed URL is pushed back.
    webhook_secret = models.CharField(max_length=64, default=_generate_webhook_secret)

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
