from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://ezo.io/ezofficeinventory/developers/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "assets": {
        "description": "Fixed (trackable) assets — individually identified items that are checked in and out.",
        "docs_url": _DOCS_URL,
        "columns": {
            "identifier": "Unique identifier (sequence number) for the asset.",
            "name": "Display name of the asset.",
            "state": "Current lifecycle state of the asset (e.g. available, checked out, in service).",
            "group_id": "Identifier of the asset group the asset belongs to.",
            "location_id": "Identifier of the location the asset is currently at.",
            "created_at": "Timestamp when the asset was created.",
            "updated_at": "Timestamp when the asset was last updated.",
        },
    },
    "inventories": {
        "description": "Inventory (volatile) items tracked by quantity rather than as individually identified units.",
        "docs_url": _DOCS_URL,
        "columns": {
            "identifier": "Unique identifier for the inventory item.",
            "name": "Display name of the inventory item.",
            "created_at": "Timestamp when the inventory item was created.",
            "updated_at": "Timestamp when the inventory item was last updated.",
        },
    },
    "asset_stocks": {
        "description": "Asset stock — quantity-tracked items that share a single asset definition across many units.",
        "docs_url": _DOCS_URL,
        "columns": {
            "identifier": "Unique identifier for the asset stock item.",
            "name": "Display name of the asset stock item.",
            "created_at": "Timestamp when the asset stock item was created.",
            "updated_at": "Timestamp when the asset stock item was last updated.",
        },
    },
    "checked_out_assets": {
        "description": "Fixed assets currently checked out, returned by the asset filter endpoint with status=checked_out.",
        "docs_url": _DOCS_URL,
        "columns": {
            "identifier": "Unique identifier (sequence number) for the asset.",
            "name": "Display name of the asset.",
            "created_at": "Timestamp when the asset was created.",
        },
    },
    "members": {
        "description": "People in the account — employees and other users who can check items in and out.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the member.",
            "email": "Member's email address.",
            "employee_identification_number": "Employee identification number.",
            "status": "Member status (e.g. active, inactive).",
            "created_at": "Timestamp when the member was created.",
        },
    },
    "locations": {
        "description": "Physical locations where assets and inventory are stored or used.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the location.",
            "name": "Display name of the location.",
            "city": "City the location is in.",
            "country": "Country the location is in.",
            "created_at": "Timestamp when the location was created.",
        },
    },
    "groups": {
        "description": "Asset groups used to categorize assets.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Display name of the group.",
            "created_at": "Timestamp when the group was created.",
        },
    },
    "subgroups": {
        "description": "Subgroups nested under asset groups for finer categorization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the subgroup.",
            "name": "Display name of the subgroup.",
            "created_at": "Timestamp when the subgroup was created.",
        },
    },
    "vendors": {
        "description": "Vendors that supply assets, inventory, and services.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the vendor.",
            "name": "Display name of the vendor.",
            "created_at": "Timestamp when the vendor was created.",
        },
    },
    "labels": {
        "description": "Print label templates configured for assets.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the label template.",
            "name": "Display name of the label template.",
        },
    },
    "custom_fields": {
        "description": "Custom attributes (fields) defined for assets in the account.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the custom field.",
            "name": "Display name of the custom field.",
        },
    },
    "purchase_orders": {
        "description": "Purchase orders raised for procuring assets and inventory.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the purchase order.",
            "created_at": "Timestamp when the purchase order was created.",
        },
    },
}
