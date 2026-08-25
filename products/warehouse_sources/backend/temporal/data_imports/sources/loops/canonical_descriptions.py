from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A marketing campaign, including its status, schedule, audience, and group.",
        "docs_url": "https://loops.so/docs/api-reference/list-campaigns",
        "columns": {
            "id": "The campaign ID.",
            "name": "The campaign name.",
            "status": "Campaign lifecycle status (for example Draft, Scheduled, Sending, Sent).",
            "createdAt": "ISO 8601 timestamp for when the campaign was created.",
            "updatedAt": "ISO 8601 timestamp for when the campaign was last updated.",
            "emailMessageId": "The associated email message ID.",
            "campaignGroupId": "The ID of the campaign group this campaign belongs to.",
            "mailingListId": "The ID of the mailing list this campaign sends to, if set.",
            "audienceSegmentId": "The ID of the audience segment this campaign targets, if set.",
            "audienceFilter": "The inline audience filter, if set.",
            "scheduling": "When the campaign is scheduled to send.",
        },
    },
    "campaign_groups": {
        "description": "A campaign group used to organize related marketing campaigns.",
        "docs_url": "https://loops.so/docs/api-reference/list-campaign-groups",
        "columns": {
            "id": "The campaign group ID.",
            "name": "The group name.",
            "description": "The group description.",
            "createdAt": "ISO 8601 timestamp for when the group was created.",
            "updatedAt": "ISO 8601 timestamp for when the group was last updated.",
        },
    },
    "mailing_lists": {
        "description": "A mailing list contacts can subscribe to.",
        "docs_url": "https://loops.so/docs/api-reference/list-mailing-lists",
        "columns": {
            "id": "The ID of the list.",
            "name": "The name of the list.",
            "description": "The list's description, or null if no description has been added.",
            "isPublic": "Whether the list is public (true) or private (false).",
        },
    },
    "audience_segments": {
        "description": "An audience segment with filter rules, used for campaign targeting.",
        "docs_url": "https://loops.so/docs/api-reference/list-audience-segments",
        "columns": {
            "id": "The audience segment ID.",
            "name": "The segment name.",
            "description": "An optional description for the segment.",
            "createdAt": "ISO 8601 timestamp for when the segment was created.",
            "updatedAt": "ISO 8601 timestamp for when the segment was last updated.",
            "filter": "The segment's audience filter.",
        },
    },
    "workflows": {
        "description": "An automation workflow in the Loops account.",
        "docs_url": "https://loops.so/docs/api-reference/list-workflows",
        "columns": {
            "id": "The workflow ID.",
            "name": "The workflow name.",
            "createdAt": "ISO 8601 timestamp for when the workflow was created.",
            "updatedAt": "ISO 8601 timestamp for when the workflow was last updated.",
        },
    },
    "transactional_emails": {
        "description": "A transactional email, including its group and current draft and published messages.",
        "docs_url": "https://loops.so/docs/api-reference/list-transactional-emails",
        "columns": {
            "id": "The transactional email ID.",
            "name": "The transactional email name.",
            "draftEmailMessageId": "The ID of the draft email message, if one exists.",
            "publishedEmailMessageId": "The ID of the published email message, if one exists.",
            "transactionalGroupId": "The ID of the group this transactional email belongs to.",
            "createdAt": "ISO 8601 timestamp for when the transactional email was created.",
            "updatedAt": "ISO 8601 timestamp for when the transactional email was last updated.",
            "dataVariables": "Data variable names used by the published email. Empty for unpublished emails.",
        },
    },
    "transactional_groups": {
        "description": "A transactional group used to organize related transactional emails.",
        "docs_url": "https://loops.so/docs/api-reference/list-transactional-groups",
        "columns": {
            "id": "The transactional group ID.",
            "name": "The group name.",
            "description": "The group description.",
            "createdAt": "ISO 8601 timestamp for when the group was created.",
            "updatedAt": "ISO 8601 timestamp for when the group was last updated.",
        },
    },
    "contact_properties": {
        "description": "A contact property (default or custom) defined in the Loops account.",
        "docs_url": "https://loops.so/docs/api-reference/list-contact-properties",
        "columns": {
            "key": "The property's name key.",
            "label": "The human-friendly label for this property.",
            "type": "The type of property (one of string, number, boolean or date).",
        },
    },
    "themes": {
        "description": "An email theme with style attributes for authored email messages.",
        "docs_url": "https://loops.so/docs/api-reference/list-themes",
        "columns": {
            "id": "The theme ID.",
            "name": "The theme name.",
            "styles": "The theme's style attributes, named after LMX Style tag attributes.",
            "isDefault": "Whether this is the account's default theme.",
            "createdAt": "ISO 8601 timestamp for when the theme was created.",
            "updatedAt": "ISO 8601 timestamp for when the theme was last updated.",
        },
    },
    "components": {
        "description": "A reusable email component available for use in LMX templates and authored email messages.",
        "docs_url": "https://loops.so/docs/api-reference/list-components",
        "columns": {
            "id": "The component ID.",
            "name": "The component name.",
            "lmx": "The component's LMX markup.",
        },
    },
}
