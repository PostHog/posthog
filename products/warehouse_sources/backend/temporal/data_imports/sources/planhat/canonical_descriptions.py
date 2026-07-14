from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Planhat API docs (https://docs.planhat.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "A customer account (company) tracked in Planhat, the core object health scores and revenue attach to.",
        "docs_url": "https://docs.planhat.com/#companies",
        "columns": {
            "_id": "The unique ID of the company.",
            "name": "The company name.",
            "externalId": "Your own identifier for the company, used to match it against your systems.",
            "phase": "The lifecycle phase of the customer.",
            "status": "The account status (for example active or churned).",
            "ownerId": "The ID of the Planhat user who owns the account.",
            "mrr": "The current monthly recurring revenue for the company.",
            "h": "The company's current health score.",
            "createDate": "When the company was created.",
            "lastUpdated": "When the company was last modified.",
        },
    },
    "endusers": {
        "description": "A contact (end user) at one of your customer companies.",
        "docs_url": "https://docs.planhat.com/#endusers",
        "columns": {
            "_id": "The unique ID of the end user.",
            "name": "The end user's full name.",
            "email": "The end user's email address.",
            "companyId": "The ID of the company the end user belongs to.",
            "companyName": "The name of the company the end user belongs to.",
            "phone": "The end user's phone number.",
            "position": "The end user's job title or role.",
            "createDate": "When the end user was created.",
            "lastUpdated": "When the end user was last modified.",
        },
    },
    "users": {
        "description": "A Planhat team member (internal user) in your workspace.",
        "docs_url": "https://docs.planhat.com/#users",
        "columns": {
            "_id": "The unique ID of the user.",
            "email": "The user's email address.",
            "firstName": "The user's first name.",
            "lastName": "The user's last name.",
            "nickName": "The user's display name.",
            "isActive": "Whether the user account is active.",
            "roles": "The roles assigned to the user.",
        },
    },
    "licenses": {
        "description": "A license or subscription line item attached to a company, driving recurring revenue.",
        "docs_url": "https://docs.planhat.com/#licenses",
        "columns": {
            "_id": "The unique ID of the license.",
            "companyId": "The ID of the company the license belongs to.",
            "product": "The product the license is for.",
            "value": "The monetary value of the license.",
            "mrr": "The monthly recurring revenue from the license.",
            "fromDate": "When the license term starts.",
            "toDate": "When the license term ends.",
            "renewalStatus": "The renewal status of the license.",
        },
    },
    "assets": {
        "description": "An asset (a sub-unit of a company such as a product instance, project, or store) tracked in Planhat.",
        "docs_url": "https://docs.planhat.com/#assets",
        "columns": {
            "_id": "The unique ID of the asset.",
            "name": "The asset name.",
            "companyId": "The ID of the company the asset belongs to.",
            "externalId": "Your own identifier for the asset.",
            "createDate": "When the asset was created.",
            "lastUpdated": "When the asset was last modified.",
        },
    },
    "nps": {
        "description": "An NPS survey response collected from an end user.",
        "docs_url": "https://docs.planhat.com/#nps",
        "columns": {
            "_id": "The unique ID of the NPS response.",
            "companyId": "The ID of the company the respondent belongs to.",
            "enduserId": "The ID of the end user who responded.",
            "campaignId": "The ID of the NPS campaign the response belongs to.",
            "score": "The NPS score given by the respondent (0-10).",
            "comment": "The free-text comment left with the score.",
            "followUp": "The follow-up status for the response.",
            "date": "When the response was submitted.",
        },
    },
}
