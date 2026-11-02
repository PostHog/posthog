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
    "form_entries": {
        "description": "An entry submitted to a Wufoo form. Each FieldN column holds the answer to one form "
        "field; join to form_fields on form_hash and ID to read the field titles.",
        "docs_url": "https://wufoo.github.io/docs/#form-entries",
        "columns": {
            "form_hash": "The hash of the form that the entry belongs to.",
            "EntryId": "The identifier of the entry, unique within its form.",
            "DateCreated": "The date and time the entry was submitted, in the timezone of the API key's user.",
            "CreatedBy": "Who created the entry: 'public' for a form submission, or the user name for an entry "
            "added in the Entry Manager.",
            "DateUpdated": "The date and time the entry was last edited in the Entry Manager; blank if never edited.",
            "UpdatedBy": "The user name of the person who last edited the entry in the Entry Manager.",
            "IP": "The IP address of the person who submitted the form.",
            "LastPage": "The last page of the form that the person submitted.",
            "CompleteSubmission": "Whether the entry is complete ('1') or partial ('0').",
            "Status": "The payment status of the entry, for example 'Paid'.",
            "PurchaseTotal": "The total amount sent to the payment processor.",
            "Currency": "The currency sent to the payment processor.",
            "TransactionId": "The confirmation number returned by the payment processor.",
            "MerchantType": "The name of the payment processor used.",
        },
    },
    "form_fields": {
        "description": "A field on a Wufoo form. Maps the FieldN column IDs on form_entries to field titles, types, "
        "and choices.",
        "docs_url": "https://wufoo.github.io/docs/#form-fields",
        "columns": {
            "form_hash": "The hash of the form that the field belongs to.",
            "ID": "The API ID of the field, for example 'Field105'. Matches a column on form_entries.",
            "Title": "The field label.",
            "Type": "The field type, for example 'text', 'checkbox', or 'radio'.",
            "Instructions": "The instructions shown to the user for this field.",
            "IsRequired": "Whether the field is required ('1') or optional ('0').",
            "ClassNames": "The CSS keywords set on the field in the Form Builder.",
            "DefaultVal": "The predefined value of the field.",
            "Page": "The page of the form that holds the field.",
            "SubFields": "The sub-fields of a multi-part field, such as checkbox options or address parts, each "
            "with its own ID and label.",
            "Choices": "The choices of a dropdown, multiple choice, or likert field.",
            "IsSystem": "Whether the field is a system field, such as IP address or payment status.",
        },
    },
    "report_entries": {
        "description": "An entry that a Wufoo report includes, after the report's filters are applied.",
        "docs_url": "https://wufoo.github.io/docs/#report-entries",
        "columns": {
            "report_hash": "The hash of the report that includes the entry.",
            "EntryId": "The identifier of the entry, unique within the report's form.",
            "DateCreated": "The date and time the entry was submitted.",
        },
    },
    "report_fields": {
        "description": "A field on the form that a Wufoo report is built on. Maps the FieldN column IDs on "
        "report_entries to field titles.",
        "docs_url": "https://wufoo.github.io/docs/#report-fields",
        "columns": {
            "report_hash": "The hash of the report.",
            "ID": "The API ID of the field, for example 'Field105'. Matches a column on report_entries.",
            "Title": "The field label.",
            "Type": "The field type, for example 'text', 'checkbox', or 'radio'.",
        },
    },
}
