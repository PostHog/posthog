from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://www.membrain.com/developers/api-documentation"

_AUDIT_COLUMNS = {
    "Id": "Unique identifier (GUID).",
    "CreatedById": "GUID of the user who created the record.",
    "CreatedByName": "Name of the user who created the record.",
    "CreatedDate": "Timestamp when the record was created.",
    "ChangedById": "GUID of the user who last changed the record.",
    "ChangedByName": "Name of the user who last changed the record.",
    "ChangedDate": "Timestamp when the record was last changed.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "Companies (accounts) in the Membrain CRM, including deleted ones.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Company name.",
            "City": "City of the company's address.",
            "CountryName": "Country of the company's address.",
            "CountryCode": "ISO country code of the company's address.",
            "EmailAddress": "Company email address.",
        },
    },
    "contacts": {
        "description": "Contacts (people) in the Membrain CRM, including deleted and retired ones. Custom field values appear as CustomField<GUID> columns.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Contact's full name.",
            "EmailAddress": "Contact's email address.",
            "CompanyId": "GUID of the company the contact belongs to.",
            "CompanyName": "Name of the company the contact belongs to.",
        },
    },
    "prospects": {
        "description": "Prospecting-pipeline items. A prospect's human-readable key has the form P-{n}.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Prospect name.",
            "CompanyId": "GUID of the related company.",
            "CompanyName": "Name of the related company.",
            "Deleted": "Whether the prospect has been deleted.",
            "DeletedDate": "Timestamp when the prospect was deleted.",
        },
    },
    "opportunities": {
        "description": "Sales projects (opportunities). A sales project's human-readable key has the form SP-{n}.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Sales project name.",
            "CompanyId": "GUID of the related company.",
            "CompanyName": "Name of the related company.",
            "EstimatedClosingDate": "Estimated closing date of the sales project.",
            "LostComment": "Comment recorded when the sales project was lost.",
            "LostReasonId": "GUID of the recorded lost reason.",
            "LostReasonName": "Name of the recorded lost reason.",
        },
    },
    "account_growth_items": {
        "description": "Account growth projects. An account growth project's human-readable key has the form AGP-{n}.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Account growth project name.",
            "CompanyId": "GUID of the related company.",
            "CompanyName": "Name of the related company.",
            "OwnerId": "GUID of the owning user.",
            "OwnerName": "Name of the owning user.",
            "ProcessId": "GUID of the account growth process the project runs in.",
            "ProcessCurrentStageId": "GUID of the project's current process stage.",
            "ProcessCurrentStageName": "Name of the project's current process stage.",
        },
    },
    "tickets": {
        "description": "Support or service tickets. A ticket's human-readable key has the form T-{n}.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Ticket name.",
            "Description": "Ticket description.",
            "CompanyId": "GUID of the related company.",
            "CompanyName": "Name of the related company.",
            "OwnerId": "GUID of the owning user.",
            "OwnerName": "Name of the owning user.",
            "Status": "Ticket status (New, Open, Pending, Resolved, or Archived).",
            "Priority": "Ticket priority (Highest, High, Medium, Low, or Lowest).",
        },
    },
    "activities": {
        "description": "Activities: tasks, appointments, calls, notes, and emails. Unset dates use the sentinel value 1753-01-01 00:00:00.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "ActivityTypeId": "GUID of the activity type.",
            "ActivityTypeName": "Name of the activity type.",
            "Contents": "Text contents of the activity.",
            "Completed": "Whether the activity has been completed.",
            "OrganizerId": "GUID of the organizing user.",
            "Deadline": "Deadline of the activity.",
        },
    },
    "users": {
        "description": "Membrain users. Every user is also a contact; additional properties such as title and phone number live on the contacts table.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier (GUID).",
            "Name": "User's full name.",
            "CompanyId": "GUID of the user's company.",
            "CompanyName": "Name of the user's company.",
            "EmailAddress": "User's email address.",
            "UserInterfaceLanguage": "Language the user's Membrain interface uses.",
            "TimeZone": "User's time zone.",
            "SalesTeams": "Sales teams the user belongs to, as a list of {Id, Name} objects.",
        },
    },
    "roles": {
        "description": "Roles that can be assigned to a stakeholder on a project (for example Accountable or Approver).",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier (GUID).",
            "Name": "Role name.",
        },
    },
    "custom_fields": {
        "description": "Custom field definitions across entity types. One row per definition, with EntityType naming the entity the field belongs to.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Unique identifier (GUID) of the field definition. Matches the GUID in CustomField<GUID> columns on entity tables.",
            "Name": "Display name of the custom field.",
            "Type": "Field type (for example Text, Date, or SingleSelect).",
            "Options": "For select types, the selectable options as a list of {Id, Name} objects.",
            "EntityType": "Entity the field belongs to (for example company, contact, or user). Added by PostHog from the response's per-entity grouping.",
        },
    },
    "products": {
        "description": "Products that can be attached to sales projects.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_AUDIT_COLUMNS,
            "Name": "Product name.",
            "Description": "Product description.",
            "Price": "Product price.",
            "PriceCurrency": "Currency of the product price.",
            "PriceType": "Pricing model of the product.",
            "Cost": "Product cost.",
        },
    },
}
