from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An X advertising campaign containing line items and funded by a funding instrument.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#campaigns",
        "columns": {
            "id": "Campaign identifier.",
            "funding_instrument_id": "Funding instrument that supplies the campaign's budget and billing currency.",
            "name": "Campaign name.",
            "deleted": "Whether the campaign has been deleted.",
        },
    },
    "line_items": {
        "description": "An ad group within an X campaign, with its objective, targeting, and bid settings.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#line-items",
        "columns": {
            "id": "Line item identifier.",
            "campaign_id": "Parent campaign identifier.",
            "objective": "Advertising objective.",
        },
    },
    "promoted_tweets": {
        "description": "An association between an X Post and the line item that promotes it.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#promoted-tweets",
        "columns": {
            "id": "Promoted Post identifier.",
            "tweet_id": "Identifier of the promoted Post.",
            "line_item_id": "Line item that promotes the Post.",
        },
    },
    "funding_instruments": {
        "description": "A payment or credit arrangement funding X advertising campaigns.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#funding-instruments",
        "columns": {
            "id": "Funding instrument identifier.",
            "currency": "ISO 4217 billing currency.",
            "type": "Funding instrument type.",
        },
    },
    "media_creatives": {
        "description": "A media creative associated with an X advertising line item.",
        "docs_url": "https://docs.x.com/x-ads-api/campaign-management/reference#media-creatives",
        "columns": {"id": "Media creative identifier.", "line_item_id": "Line item that promotes the creative."},
    },
    **{
        table: {
            "description": f"Daily unsegmented X advertising metrics for a {entity}, separated by placement.",
            "docs_url": "https://docs.x.com/x-ads-api/analytics",
            "columns": {
                "entity_id": f"Identifier of the {entity} whose metrics are reported.",
                "date": "Report day in the ad account's reporting timezone.",
                "placement": "Advertising placement for these metrics.",
                "billed_charge_local_micro": "Billed spend in millionths of the funding instrument's currency.",
                "currency": "ISO 4217 billing currency from the campaign's funding instrument.",
                "impressions": "Number of times the ad was served.",
                "clicks": "Total clicks, including favorites and other engagements.",
            },
        }
        for table, entity in (("campaign_stats", "campaign"), ("line_item_stats", "line item"))
    },
}
