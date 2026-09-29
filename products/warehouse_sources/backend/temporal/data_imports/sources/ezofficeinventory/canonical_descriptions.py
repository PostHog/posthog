from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://ezo.io/ezofficeinventory/developers/"
# Work orders and the history sub-resources are documented on the v2 reference only.
_DOCS_URL_V2 = "https://ezo.io/ezofficeinventory/api-v2/"

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
    "teams": {
        "description": "Teams that members are grouped into. Resolves the team ids carried on member records.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Display name of the team.",
            "description": "Free-text description of the team.",
            "parent_id": "Identifier of the parent team, for teams nested under another team.",
            "identification_number": "Identification number assigned to the team.",
        },
    },
    "work_orders": {
        "description": "Work orders (maintenance, repair and service tasks) raised against assets or locations.",
        "docs_url": _DOCS_URL_V2,
        "columns": {
            "id": "Unique identifier for the work order.",
            "title": "Summary of the work to be done.",
            "state": "Current state of the work order (e.g. open, in progress, review pending, completed).",
            "priority": "Priority of the work order (high, medium or low).",
            "task_type": "Work order type, the primary breakdown dimension for work orders.",
            "task_type_id": "Identifier of the work order type.",
            "assigned_to_id": "Identifier of the member or team the work order is assigned to.",
            "assigned_to_type": "Whether the work order is assigned to a member or a team.",
            "reviewer_id": "Identifier of the member who reviews the completed work order.",
            "location_id": "Identifier of the location the work order applies to.",
            "project_id": "Identifier of the project the work order is linked to.",
            "expected_start_date": "Date the work was expected to start.",
            "due_date": "Date the work order is due for completion.",
            "started_on": "Timestamp when work on the work order started.",
            "completed_on": "Timestamp when the work order was completed.",
            "time_spent": "Total time logged against the work order, in hours.",
            "base_cost": "Labour or base cost recorded on the work order.",
            "inventory_cost": "Cost of inventory consumed by the work order.",
            "total_cost": "Total cost of the work order, including inventory and work logs.",
            "created_at": "Timestamp when the work order was created.",
            "updated_at": "Timestamp when the work order was last updated.",
        },
    },
    "asset_checkout_history": {
        "description": (
            "Check-in and check-out transitions per fixed asset — the utilization history behind "
            "how long each asset was held and by whom."
        ),
        "docs_url": _DOCS_URL_V2,
        "columns": {
            "asset_id": "Identifier of the asset this history entry belongs to, taken from the parent asset record.",
            "id": "Identifier of the history entry within its asset.",
            "is_checkout": "Whether the entry records a check-out rather than a check-in.",
            "assigned_to_id": "Identifier of the member, team or location the asset was assigned to.",
            "assigned_to_type": "What kind of entity the asset was assigned to.",
            "assigned_to_name": "Display name of the entity the asset was assigned to.",
            "checkout_on": "Timestamp when the asset was checked out.",
            "checkin_due_on": "Timestamp the asset was due back.",
            "checkin_on": "Timestamp the asset was expected to be checked in.",
            "actual_checkin_on": "Timestamp the asset was actually checked in.",
            "checked_out_duration_in_seconds": "How long the asset stayed checked out, in seconds.",
            "location_id": "Identifier of the location involved in the transition.",
            "project_id": "Identifier of the project the checkout was linked to.",
            "is_transfer": "Whether the entry records a transfer rather than a plain check-in or check-out.",
            "action_source": "Where the transition was made from (e.g. Web App).",
            "created_at": "Timestamp when the history entry was created.",
            "updated_at": "Timestamp when the history entry was last updated.",
        },
    },
    "member_stock_histories": {
        "description": (
            "Stock transactions attributed to a member — checkouts, check-ins, transfers and stock "
            "adjustments against quantity-tracked items."
        ),
        "docs_url": _DOCS_URL_V2,
        "columns": {
            "member_id": "Identifier of the member this entry belongs to, taken from the parent member record.",
            "id": "Identifier of the stock history entry within its member.",
            "order_type": "Kind of stock transaction (e.g. Add Stock, checkin, New Sale).",
            "asset_name": "Display name of the item the transaction applies to.",
            "quantity": "Quantity moved by the transaction.",
            "quantity_after_transaction": "Quantity remaining on the item after the transaction.",
            "price": "Unit price recorded on the transaction.",
            "cost_price": "Total cost recorded on the transaction.",
            "unit_cost_price": "Cost per unit recorded on the transaction.",
            "checkout_on": "Timestamp the stock was checked out.",
            "checkin_due_on": "Timestamp the stock was due back.",
            "checkin_on": "Timestamp the stock was checked in.",
            "checked_out_to_location_id": "Identifier of the location the stock was checked out to.",
            "checked_in_from_location_id": "Identifier of the location the stock was checked in from.",
            "purchase_order_id": "Identifier of the purchase order the stock came in on.",
            "vendor_id": "Identifier of the vendor the stock was bought from.",
            "project_id": "Identifier of the project the transaction was linked to.",
            "task_id": "Identifier of the work order that consumed the stock.",
            "created_at": "Timestamp when the transaction was recorded.",
            "updated_at": "Timestamp when the transaction was last updated.",
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
