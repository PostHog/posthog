from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "signature_requests": {
        "description": (
            "A signature request groups the documents to sign, the signers, and optional "
            "approvers, and tracks the signing process from draft to completion."
        ),
        "docs_url": "https://developers.yousign.com/reference/get-signature_requests-1",
        "columns": {
            "id": "Unique identifier of the signature request.",
            "status": (
                "Lifecycle status: draft, ongoing, done, deleted, expired, canceled, approval, "
                "rejected, declined, or paused."
            ),
            "name": "Name of the signature request.",
            "delivery_mode": "How signers are notified: email, or none for API-driven flows.",
            "created_at": "When the signature request was created.",
            "activated_at": "When the signature request was activated and sent to signers.",
            "completed_at": "When every signer completed their signature.",
            "approved_at": "When every approver approved the request.",
            "ordered_signers": "Whether signers must sign in a set order.",
            "timezone": "Timezone used for dates shown to recipients.",
            "expiration_date": "When the signature request expires.",
            "source": "Application that created the request (app, public_api, or a connector).",
            "signers": "Embedded signer references with their per-signer status.",
            "approvers": "Embedded approver references with their per-approver status.",
            "documents": "Embedded document references with their nature.",
            "labels": "Labels attached to the signature request.",
            "sender": "User who sent the signature request.",
            "external_id": "Caller-supplied identifier for correlating with external systems.",
            "workspace_id": "Workspace the signature request belongs to.",
            "audit_trail_locale": "Language of the generated audit trail.",
        },
    },
    "signers": {
        "description": (
            "A signer of a signature request, with their identity details, signature level, "
            "authentication mode, and signing status."
        ),
        "docs_url": "https://developers.yousign.com/reference/get-signature_requests-signaturerequestid-signers-1",
        "columns": {
            "id": "Unique identifier of the signer.",
            "signature_request_id": "Signature request this signer belongs to.",
            "info": "Signer identity: first name, last name, email, phone number, and locale.",
            "status": (
                "Signing status: initiated, declined, notified, verified, processing, "
                "consent_given, signed, aborted, or error."
            ),
            "signature_level": (
                "eIDAS signature level: electronic_signature, advanced_electronic_signature, "
                "or qualified_electronic_signature."
            ),
            "signature_authentication_mode": "How the signer is authenticated: otp_email, otp_sms, or no_otp.",
            # signature_link is intentionally not imported — it is a directly usable signing URL
            # (see yousign.SIGNER_CAPABILITY_FIELDS), so it is stripped before rows are persisted.
            "signature_link_expiration_date": "When the signer's (non-imported) signature link expires.",
            "delivery_mode": "How this signer is notified: email, or none.",
            "fields": "Fields placed on the documents for this signer.",
            "signed_at": "When the signer completed their signature.",
            "recipient_stage_index": "Notification stage; recipients sharing an index are notified together.",
        },
    },
    "documents": {
        "description": "A document attached to a signature request, either signable or a simple attachment.",
        "docs_url": "https://developers.yousign.com/reference/get-signature_requests-signaturerequestid-documents-1",
        "columns": {
            "id": "Unique identifier of the document.",
            "signature_request_id": "Signature request this document belongs to.",
            "filename": "Original file name of the document.",
            "nature": "Document nature: signable_document or attachment.",
            "content_type": "MIME type of the document, e.g. application/pdf.",
            "sha256": "SHA-256 checksum of the document content.",
            "is_signed": "Whether the document has been signed.",
            "is_protected": "Whether the document is password-protected.",
            "created_at": "When the document was uploaded.",
            "total_pages": "Number of pages of a signable document.",
        },
    },
    "contacts": {
        "description": "A contact saved in the organization's contact book, reusable as a recipient.",
        "docs_url": "https://developers.yousign.com/reference/get-contacts-1",
        "columns": {
            "id": "Unique identifier of the contact.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "email": "Contact's email address.",
            "phone_number": "Contact's phone number in E.164 format.",
            "locale": "Contact's preferred language.",
            "company_name": "Company the contact belongs to.",
            "job_title": "Contact's job title.",
            "workspace_id": "Workspace the contact belongs to, if workspace-scoped.",
        },
    },
    "users": {
        "description": "A member of the Yousign organization.",
        "docs_url": "https://developers.yousign.com/reference/get-users-1",
        "columns": {
            "id": "Unique identifier of the user.",
            "first_name": "User's first name.",
            "last_name": "User's last name.",
            "email": "User's email address.",
            "role": "Organization role: owner, admin, or member.",
            "status": "Account status: invited, signed_up, verified, or completed.",
            "is_active": "Whether the user account is active.",
            "created_at": "When the user was created.",
            "workspaces": "Workspaces the user belongs to.",
        },
    },
    "workspaces": {
        "description": "A workspace used to partition members, signature requests, and contacts.",
        "docs_url": "https://developers.yousign.com/reference/get-workspaces-1",
        "columns": {
            "id": "Unique identifier of the workspace.",
            "name": "Internal name of the workspace.",
            "external_name": "Name shown to recipients, when different from the internal name.",
            "default": "Whether this is the organization's default workspace.",
            "created_at": "When the workspace was created.",
            "updated_at": "When the workspace was last updated.",
            "users": "Members of the workspace.",
        },
    },
    "labels": {
        "description": "A label used to organize and filter signature requests.",
        "docs_url": "https://developers.yousign.com/reference/get-labels",
        "columns": {
            "id": "Unique identifier of the label.",
            "name": "Name of the label.",
            "created_at": "When the label was created.",
        },
    },
}
