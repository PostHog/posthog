from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Wufoo REST API v3 docs (https://www.wufoo.com/docs/api/v3/).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "forms": {
        "description": "A Wufoo form — the definition of a form used to collect entries, including its "
        "URL, status, and settings.",
        "docs_url": "https://www.wufoo.com/docs/api/v3/forms/",
        "columns": {
            "Name": "The name of the form.",
            "Description": "The form's description.",
            "RedirectMessage": "The confirmation message shown after a submission (when no redirect URL is set).",
            "Url": "The URL slug of the form.",
            "Email": "The email address that submission notifications are sent to.",
            "IsPublic": "Whether the form is publicly accessible ('1') or disabled ('0').",
            "Language": "The language the form is presented in.",
            "StartDate": "The date the form starts accepting entries.",
            "EndDate": "The date the form stops accepting entries.",
            "EntryLimit": "The maximum number of entries the form will accept ('0' = unlimited).",
            "EntryCountToday": "The number of entries submitted to the form today.",
            "DateCreated": "The date and time the form was created.",
            "DateUpdated": "The date and time the form was last updated.",
            "Hash": "The unique hash identifying the form; used as the parent key for its entries and fields.",
        },
    },
    "reports": {
        "description": "A Wufoo report — a saved visualization/summary built on top of a form's entries.",
        "docs_url": "https://www.wufoo.com/docs/api/v3/reports/",
        "columns": {
            "Name": "The name of the report.",
            "Description": "The report's description.",
            "IsPublic": "Whether the report is publicly accessible ('1') or private ('0').",
            "Url": "The URL slug of the report.",
            "DateCreated": "The date and time the report was created.",
            "DateUpdated": "The date and time the report was last updated.",
            "Hash": "The unique hash identifying the report.",
        },
    },
    "users": {
        "description": "A user on the Wufoo account, with their role and access level.",
        "docs_url": "https://www.wufoo.com/docs/api/v3/users/",
        "columns": {
            "User": "The username of the account user.",
            "Email": "The user's email address.",
            "Type": "The user's account role (e.g. Administrator).",
            "AccountUserId": "The numeric ID of the user within the account.",
            "Hash": "The unique hash identifying the user.",
            "Image": "The URL of the user's avatar image.",
            "IsAccountOwner": "Whether the user owns the account ('1') or not ('0').",
            "IsAdmin": "Whether the user has administrator access ('1') or not ('0').",
            "TimeZone": "The user's configured time zone.",
        },
    },
}
