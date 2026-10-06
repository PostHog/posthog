from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Active direct mail campaigns in the Poplar account.",
        "docs_url": "https://docs.heypoplar.com/api/endpoints/other-endpoints",
        "columns": {
            "id": "Campaign identifier.",
            "name": "Campaign name.",
        },
    },
    "campaign_creatives": {
        "description": "Active creatives (the artwork that is printed and mailed) for each active campaign.",
        "docs_url": "https://docs.heypoplar.com/api/endpoints/other-endpoints",
        "columns": {
            "campaign_id": "Campaign the creative belongs to.",
            "id": "Creative identifier.",
            "name": "Creative name.",
            "mail_type": "Postage class, for example USPS First Class.",
            "creative_type": "Mail format and size, for example 6x9 Postcard.",
            "merge_tags": "Custom merge tags used by a dynamic HTML creative.",
            "thumbnail_url": "URL of a preview image of the creative.",
            "default": "Whether this creative is used when a mailing does not name one.",
            "format": "File format of the creative, for example PDF.",
            "image_formats": "File formats of the creative's images.",
        },
    },
    "campaign_mailings": {
        "description": "Individual mail pieces sent or scheduled for each active campaign, with their delivery state and cost.",
        "docs_url": "https://docs.heypoplar.com/api/endpoints/other-endpoints",
        "columns": {
            "id": "Mailing identifier.",
            "campaign_id": "Campaign the mailing belongs to.",
            "creative_id": "Creative used for the mailing.",
            "merge_tags": "Merge tag values supplied for this mailing.",
            "state": "Current state of the mailing: processing, production, in_transit, delivered, holdout, suppressed, or exception.",
            "front_url": "URL of the front preview image. Expires 30 days after the mailing is created.",
            "back_url": "URL of the back preview image. Expires 30 days after the mailing is created.",
            "pdf_url": "URL of the PDF preview. Expires 30 days after the mailing is created.",
            "total_cost": "Cost of the mailing in USD, as a decimal string.",
            "send_at": "When the mailing is scheduled to be sent, or null if it was sent immediately.",
            "created_at": "When the mailing was created, in UTC.",
            "address": "Recipient name and postal address printed on the mailing.",
        },
    },
    "campaign_stats": {
        "description": "Lifetime circulation and spend for each campaign, one row per campaign.",
        "docs_url": "https://docs.heypoplar.com/api/endpoints/stats",
        "columns": {
            "campaign_id": "Campaign identifier.",
            "campaign_name": "Campaign name.",
            "circulation": "Total number of pieces mailed for the campaign.",
            "spend": "Total spend for the campaign in USD.",
        },
    },
    "audiences": {
        "description": "Mailing and suppression lists stored in the Poplar account, including the Do Not Mail list.",
        "docs_url": "https://docs.heypoplar.com/api/endpoints/audience",
        "columns": {
            "id": "Audience identifier.",
            "name": "Audience name.",
            "description": "Audience description.",
            "member_count": "Number of members in the audience.",
        },
    },
}
