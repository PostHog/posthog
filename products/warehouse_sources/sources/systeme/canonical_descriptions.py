from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "Contacts with registration details, email status, custom fields, and tags.",
        "docs_url": "https://developer.systeme.io/reference/api_contacts_get_collection-1",
        "columns": {
            "id": "Unique contact identifier.",
            "email": "Contact email address.",
            "registeredAt": "Date and time of contact registration.",
            "locale": "Contact language code.",
            "sourceURL": "URL associated with the contact source.",
            "unsubscribed": "Whether the contact has unsubscribed.",
            "bounced": "Whether email to the contact has bounced.",
            "needsConfirmation": "Whether the contact needs confirmation.",
            "fields": "Custom fields and their values for the contact.",
            "tags": "Tags assigned to the contact.",
        },
    },
    "tags": {
        "description": "Tags used to organize contacts.",
        "docs_url": "https://developer.systeme.io/reference/api_tags_get_collection-1",
        "columns": {
            "id": "Unique tag identifier.",
            "name": "Tag name.",
            "createdAt": "Date and time when the tag was created.",
        },
    },
    "newsletters": {
        "description": "Email newsletters with content metadata and sending status.",
        "docs_url": "https://developer.systeme.io/reference/api_mailingnewsletters_get_collection",
        "columns": {
            "id": "Unique newsletter identifier.",
            "type": "Newsletter type.",
            "content": "Newsletter subject, preview text, editor type, and sender details.",
            "state": "Whether the newsletter has been sent.",
        },
    },
    "courses": {
        "description": "Courses with language, address, status, and module details.",
        "docs_url": "https://developer.systeme.io/reference/api_schoolcourses_get_collection-1",
        "columns": {
            "id": "Unique course identifier.",
            "name": "Course name.",
            "description": "Course description.",
            "locale": "Course language code.",
            "domainName": "Domain used by the course.",
            "path": "Course URL path.",
            "active": "Whether the course is active.",
            "modules": "Course modules with their identifiers and names.",
        },
    },
    "enrollments": {
        "description": "Contact enrollments in courses.",
        "docs_url": "https://developer.systeme.io/reference/api_schoolenrollments_get_collection-1",
        "columns": {
            "id": "Unique enrollment identifier.",
            "contact": "Contact enrolled in the course.",
            "course": "Course associated with the enrollment.",
            "accessType": "Type of access granted by the enrollment.",
            "active": "Whether the enrollment is active.",
        },
    },
    "communities": {
        "description": "Communities available in the account.",
        "docs_url": "https://developer.systeme.io/reference/api_communitycommunities_get_collection-1",
        "columns": {
            "id": "Unique community identifier.",
            "name": "Community name.",
            "domainName": "Domain used by the community.",
            "path": "Community URL path.",
        },
    },
    "memberships": {
        "description": "Contact memberships in communities.",
        "docs_url": "https://developer.systeme.io/reference/api_communitymemberships_get_collection-1",
        "columns": {
            "id": "Unique membership identifier.",
            "community": "Community associated with the membership.",
            "contact": "Contact associated with the membership.",
        },
    },
    "digital_products": {
        "description": "Digital products sold through creator stores, funnels, or white-label areas.",
        "docs_url": "https://developer.systeme.io/reference/api_paymentdigital-products_get_collection",
        "columns": {
            "id": "Unique digital product identifier.",
            "name": "Digital product name.",
            "source": "Area the digital product comes from: digital-store, funnel, or Whitelabel.",
            "createdAt": "Date and time the digital product was created.",
            "pricePlansCount": "Number of price plans attached to the digital product.",
            "resourcesCount": "Number of resources attached to the digital product.",
            "confirmationEmailId": "Identifier of the confirmation email sent after purchase.",
        },
    },
    "physical_products": {
        "description": "Physical products with SKU, price, and stock details.",
        "docs_url": "https://developer.systeme.io/reference/api_paymentphysical-products_get_collection",
        "columns": {
            "id": "Unique physical product identifier.",
            "name": "Physical product name.",
            "createdAt": "Date and time the physical product was created.",
            "updatedAt": "Date and time the physical product was last updated.",
            "sku": "Stock keeping unit of the physical product.",
            "currency": "Currency code of the product price.",
            "price": "Product price in the smallest currency unit.",
            "limitStock": "Whether the stock of the product is limited.",
            "stock": "Number of units in stock when the stock is limited.",
        },
    },
    "campaigns": {
        "description": "Automated email campaigns that send a sequence of steps to contacts.",
        "docs_url": "https://developer.systeme.io/reference/api_mailingcampaigns_get_collection",
        "columns": {
            "id": "Unique campaign identifier.",
            "name": "Campaign name.",
            "senderEmail": "Email address the campaign sends from.",
        },
    },
    "campaign_steps": {
        "description": "Email steps of each campaign, with content metadata and position in the sequence.",
        "docs_url": "https://developer.systeme.io/reference/api_mailingcampaigns_campaignidsteps_get_collection",
        "columns": {
            "id": "Unique campaign step identifier.",
            "campaignId": "Identifier of the campaign that contains the step.",
            "content": "Step email subject, preview text, editor type, and sender details.",
            "state": "Whether the step is active, and its position in the campaign.",
        },
    },
}
