"""Canonical, documentation-sourced descriptions for Paperform endpoints and columns.

Sourced from the official Paperform API reference (https://paperform.readme.io). Keyed by the
endpoint names in `settings.py` `PAPERFORM_ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced Paperform table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "forms": {
        "description": "A Paperform form with its slugs, sharing URLs, tags, and submission count.",
        "docs_url": "https://paperform.readme.io/reference/listforms",
        "columns": {
            "id": "Unique identifier of the form.",
            "slug": "The default generated slug for the form.",
            "custom_slug": "The custom slug for the form if set.",
            "space_id": "ID of the space which contains the form.",
            "title": "The title of the form.",
            "description": "The description of the form.",
            "cover_image_url": "The cover image for the form.",
            "url": "The main sharing URL for the form.",
            "additional_urls": "Additional URLs for the form.",
            "live": "Whether the form is currently accepting submissions.",
            "tags": "The tags assigned to the form.",
            "submission_count": "The number of submissions the form has received.",
            "created_at": "Time the form was created, in the account timezone.",
            "updated_at": "Time the form was last updated, in the account timezone.",
            "account_timezone": "The configured timezone for the account.",
            "created_at_utc": "Time the form was created, in UTC.",
            "updated_at_utc": "Time the form was last updated, in UTC.",
        },
    },
    "form_fields": {
        "description": "A field (question) on a Paperform form, such as a text input, dropdown, or signature.",
        "docs_url": "https://paperform.readme.io/reference/listformfields",
        "columns": {
            "form_id": "ID of the form this field belongs to.",
            "key": "The unique key for this field within its form.",
            "custom_key": "The custom key of this field.",
            "title": "The title of this field.",
            "description": "The description of this field.",
            "required": "Whether this field is required.",
            "placeholder": "The placeholder for this field.",
            "type": "The type of field (e.g. text, email, choices, signature).",
        },
    },
    "submissions": {
        "description": "A completed submission to a Paperform form, including the answers, device, and any charge.",
        "docs_url": "https://paperform.readme.io/reference/listformsubmissions",
        "columns": {
            "id": "Unique identifier of the submission.",
            "form_id": "ID of the form for the submission.",
            "data": "The answers from the form, keyed by field key.",
            "device": "Information about the device which made the submission.",
            "charge": "Details of any payment charged with the submission.",
            "pdfs": "The PDFs generated for the submission.",
            "created_at": "Time the submission was made, in the account timezone.",
            "account_timezone": "The configured timezone for the account.",
            "created_at_utc": "Time the submission was made, in UTC.",
        },
    },
    "partial_submissions": {
        "description": "An in-progress (not yet submitted) response to a Paperform form, with the answers so far.",
        "docs_url": "https://paperform.readme.io/reference/listformpartialsubmissions",
        "columns": {
            "id": "Unique identifier of the partial submission.",
            "form_id": "ID of the form for the partial submission.",
            "data": "The answers so far, keyed by field key.",
            "last_answered": "The last field the respondent answered.",
            "submitted_at": "Time the partial submission was completed, if it was, in the account timezone.",
            "created_at": "Time the partial submission was created, in the account timezone.",
            "updated_at": "Time the partial submission was last updated, in the account timezone.",
            "account_timezone": "The configured timezone for the account.",
            "submitted_at_utc": "Time the partial submission was completed, if it was, in UTC.",
            "created_at_utc": "Time the partial submission was created, in UTC.",
            "updated_at_utc": "Time the partial submission was last updated, in UTC.",
        },
    },
    "products": {
        "description": "A product sold through a Paperform form's payment fields.",
        "docs_url": "https://paperform.readme.io/reference/listformproducts",
        "columns": {
            "form_id": "ID of the form this product belongs to.",
            "SKU": "Product SKU, unique within its form.",
            "name": "Product name.",
            "price": "Product price.",
            "quantity": "Product quantity available.",
            "minimum": "Minimum number of this product that can be selected.",
            "maximum": "Maximum number of this product that can be selected.",
        },
    },
    "coupons": {
        "description": "A discount coupon configured on a Paperform form.",
        "docs_url": "https://paperform.readme.io/reference/listformcoupons",
        "columns": {
            "form_id": "ID of the form this coupon belongs to.",
            "code": "The coupon code, unique within its form.",
            "enabled": "Whether the coupon is enabled.",
            "target": "The target of the coupon (price or subscription).",
            "discountAmount": "The discount as an amount.",
            "discountPercentage": "The discount as a percentage.",
            "expiresAt": "The date and time when the coupon expires.",
        },
    },
    "spaces": {
        "description": "A Paperform space used to organize forms. Requires a Business or Agency plan.",
        "docs_url": "https://paperform.readme.io/reference/listspaces",
        "columns": {
            "id": "Unique identifier of the space.",
            "name": "The name of the space.",
            "created_at": "Time the space was created, in the account timezone.",
            "updated_at": "Time the space was last updated, in the account timezone.",
            "account_timezone": "The configured timezone for the account.",
            "created_at_utc": "Time the space was created, in UTC.",
            "updated_at_utc": "Time the space was last updated, in UTC.",
        },
    },
}
