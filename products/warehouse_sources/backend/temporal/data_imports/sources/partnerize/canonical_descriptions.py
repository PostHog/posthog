from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Campaigns the partner is approved to promote, with tracking, commission, and invoicing settings.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20Campaigns",
        "columns": {
            "campaign_id": "Unique identifier for the campaign.",
            "advertiser_id": "Identifier of the brand (advertiser) that owns the campaign.",
            "title": "Display title of the campaign.",
            "status": "Status of the campaign (a = active).",
            "publisher_status": "The partner's participation status on the campaign (a = approved, p = pending, r = rejected).",
            "conversion_type": "Type of conversion the campaign tracks (e.g. sale, lead).",
            "default_currency": "Default currency for the campaign's commissions.",
            "default_commission_rate": "Default commission rate applied to conversions.",
            "cookie_period": "Cookie lifetime for attribution, in days.",
            "destination_url": "Default landing page URL for the campaign.",
            "tracking_method": "How conversions are tracked (e.g. s2s for server-to-server).",
            "reporting_timezone": "Timezone the campaign reports in.",
            "vertical_name": "Industry vertical the campaign belongs to.",
        },
    },
    "conversions": {
        "description": "Conversions (sales, leads) attributed to the partner, with commission values, statuses, per-item breakdowns, and the originating click.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/partner-conversions",
        "columns": {
            "conversion_id": "Unique identifier for the conversion.",
            "campaign_id": "Identifier of the campaign the conversion belongs to.",
            "publisher_id": "Identifier of the partner credited with the conversion.",
            "conversion_time": "Datetime the conversion occurred.",
            "last_modified": "Datetime the conversion was last updated (e.g. a status change).",
            "currency": "Currency of the conversion value.",
            "conversion_value": "Total value of the conversion, with commission and status breakdowns.",
            "conversion_items": "Per-item breakdown of the conversion, including SKU, value, commission, and item status.",
            "conversion_reference": "The brand's reference for the conversion (e.g. order ID).",
            "publisher_reference": "The partner's own reference attached to the originating click.",
            "advertiser_reference": "Reference the brand attached to the conversion.",
            "customer_reference": "The brand's reference for the customer.",
            "customer_type": "Whether the customer was new or existing.",
            "click": "The originating click, including its set time and click reference.",
            "country": "ISO country code where the conversion happened.",
            "conversion_type": "Type of conversion (maps to the conversion_types reference table).",
            "ref_device_id": "Device the conversion happened on (maps to the devices reference table).",
            "ref_traffic_source_id": "Traffic source of the conversion (maps to the traffic_sources reference table).",
            "ref_partnership_model_id": "Partnership model of the conversion (maps to the partnership_models reference table).",
            "ref_conversion_metric_id": "Conversion metric (maps to the conversion_metrics reference table).",
            "ref_user_context_id": "User context of the conversion (maps to the user_contexts reference table).",
            "campaign_title": "Display title of the campaign at report time.",
            "publisher_name": "Display name of the partner at report time.",
            "referer_ip": "IP address the conversion request came from.",
            "source_referer": "Referring URL for the conversion.",
        },
    },
    "clicks": {
        "description": "Clicks recorded on the partner's tracking links, with device, traffic source, and referer detail.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/partner-clicks",
        "columns": {
            "clickref": "Partnerize's reference for the click; conversions link back to it.",
            "campaign_id": "Identifier of the campaign the click belongs to.",
            "publisher_id": "Identifier of the partner whose link was clicked.",
            "set_time": "Datetime the click was first recorded.",
            "set_ip": "IP address the click came from.",
            "last_used": "When the click was last used for attribution.",
            "last_ip": "IP address of the most recent use of the click.",
            "type": "Type of click (e.g. standard).",
            "status": "Processing status of the click.",
            "publisher_reference": "The partner's own reference attached to the click.",
            "referer": "Referring URL for the click.",
            "creative_id": "Identifier of the creative the click came from, if any.",
            "ref_device_id": "Device the click happened on (maps to the devices reference table).",
            "ref_traffic_source_id": "Traffic source of the click (maps to the traffic_sources reference table).",
            "ref_partnership_model_id": "Partnership model of the click (maps to the partnership_models reference table).",
            "ref_user_context_id": "User context of the click (maps to the user_contexts reference table).",
        },
    },
    "countries": {
        "description": "Reference list of countries with ISO codes, currency, and geographic metadata.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20all%20Countries",
        "columns": {
            "ref_country_id": "Unique identifier for the country.",
            "iso": "Two-letter ISO 3166-1 country code.",
            "iso3": "Three-letter ISO 3166-1 country code.",
            "printable_name": "Human-readable country name.",
            "currency_iso": "ISO code of the country's currency.",
            "continent_name": "Name of the country's continent.",
        },
    },
    "currencies": {
        "description": "Reference list of currencies supported by Partnerize.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20all%20Currencies",
        "columns": {
            "currency_id": "Unique identifier for the currency (its ISO code).",
        },
    },
    "devices": {
        "description": "Reference list of device types clicks and conversions are attributed to.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20all%20Devices",
        "columns": {
            "ref_device_id": "Unique identifier for the device type.",
        },
    },
    "timezones": {
        "description": "Reference list of timezones available for campaign reporting.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20all%20Timezones",
        "columns": {
            "ref_timezone_id": "Unique identifier for the timezone.",
        },
    },
    "traffic_sources": {
        "description": "Reference list of traffic sources clicks and conversions are attributed to.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20Traffic%20Sources",
        "columns": {
            "ref_traffic_source_id": "Unique identifier for the traffic source.",
        },
    },
    "user_contexts": {
        "description": "Reference list of user contexts (environments such as web or in-app) for attribution.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20all%20User%20Contexts",
        "columns": {
            "ref_user_context_id": "Unique identifier for the user context.",
        },
    },
    "conversion_types": {
        "description": "Reference list of conversion types (e.g. sale, lead) used by campaigns.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20Conversion%20Type",
        "columns": {
            "conversion_type_id": "Unique identifier for the conversion type.",
        },
    },
    "conversion_metrics": {
        "description": "Reference list of conversion metrics used to classify conversions.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20Conversion%20Metrics",
        "columns": {
            "ref_conversion_metric_id": "Unique identifier for the conversion metric.",
        },
    },
    "partnership_models": {
        "description": "Reference list of partnership models (e.g. affiliate, influencer) for attribution.",
        "docs_url": "https://api-docs.partnerize.com/partner/#operation/List%20Partnership%20Models",
        "columns": {
            "ref_partnership_model_id": "Unique identifier for the partnership model.",
        },
    },
}
