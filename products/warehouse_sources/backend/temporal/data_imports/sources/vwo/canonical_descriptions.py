from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "The VWO workspace selected for this connection.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-current-account-information",
        "columns": {
            "id": "Workspace identifier.",
            "name": "Workspace name.",
            "createdOn": "Workspace creation time in Unix seconds.",
            "created_at": "Workspace creation time in UTC.",
            "timezone": "Workspace timezone.",
            "enabled": "Whether the workspace is enabled.",
        },
    },
    "campaigns": {
        "description": "Experiments and campaigns in the selected VWO workspace.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-the-campaigns-of-an-account",
        "columns": {
            "id": "Campaign identifier within the workspace.",
            "name": "Campaign name.",
            "type": "Campaign type.",
            "platform": "Platform on which the campaign runs.",
            "status": "Campaign status.",
            "createdOn": "Campaign creation time in Unix seconds.",
            "created_at": "Campaign creation time in UTC.",
            "isDeleted": "Whether the campaign is deleted.",
        },
    },
    "campaign_sections": {
        "description": "Page sections used by VWO campaigns, with their nested variations.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-all-the-sections-of-a-campaign",
        "columns": {
            "id": "Section identifier within its campaign.",
            "campaign_id": "Identifier of the parent campaign.",
            "name": "Section name.",
            "cssSelector": "CSS selector for the section.",
            "variations": "Variations configured for the section.",
        },
    },
    "feature_flags": {
        "description": "Feature flags in the selected VWO workspace, including variables and variations.",
        "docs_url": "https://developers.wingify.com/v2/reference/fme-get-all-feature-flags-of-a-workspace",
        "columns": {
            "id": "Feature flag identifier.",
            "featureKey": "Unique feature flag key.",
            "name": "Feature flag name.",
            "description": "Feature flag description.",
            "variables": "Variables configured for the feature flag.",
            "rulesCount": "Number of rules configured for the feature flag.",
        },
    },
    "goals": {
        "description": "Conversion goals configured for VWO campaigns.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-all-the-goals-of-a-campaign",
        "columns": {
            "id": "Goal identifier within its campaign.",
            "campaign_id": "Identifier of the parent campaign.",
            "name": "Goal name.",
            "type": "Conversion goal type.",
            "isPrimary": "Whether this is the primary campaign goal.",
            "urls": "URL rules included in the goal.",
        },
    },
    "metric_reports": {
        "description": "Insights metric reports, including their goals and time intervals.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-all-metric-reports",
        "columns": {
            "id": "Metric report identifier.",
            "name": "Metric report name.",
            "status": "Metric report status.",
            "createdOn": "Report creation time in Unix seconds.",
            "created_at": "Report creation time in UTC.",
            "goals": "Goals associated with the report.",
            "dataIntervalRange": "Time interval covered by the report.",
        },
    },
    "variations": {
        "description": "Variations configured for VWO campaigns.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-all-the-variations-of-a-campaign",
        "columns": {
            "id": "Variation identifier within its campaign section.",
            "campaign_id": "Identifier of the parent campaign.",
            "sectionId": "Campaign section identifier. Missing identifiers use zero.",
            "name": "Variation name.",
            "isControl": "Whether this is the control variation.",
            "isDisabled": "Whether the variation is disabled.",
            "percentSplit": "Percentage of campaign traffic assigned to the variation.",
        },
    },
    "websites": {
        "description": "Websites registered in the selected VWO workspace.",
        "docs_url": "https://developers.wingify.com/v2/reference/get-all-websites",
        "columns": {
            "id": "Website identifier within the workspace.",
            "accountId": "Workspace identifier.",
            "name": "Website name.",
            "domain": "Website domain.",
            "createdAt": "Website creation time in Unix seconds.",
            "created_at": "Website creation time in UTC.",
            "isArchived": "Whether the website is archived.",
        },
    },
}
