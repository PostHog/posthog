"""Canonical, documentation-sourced descriptions for Fleetio endpoints and columns.

Sourced from the official Fleetio API reference (https://developer.fleetio.com/docs/api).
Keyed by the endpoint names in `settings.py` `FLEETIO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Fleetio table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_COMMON_COLUMNS = {
    "id": "Unique identifier for the record in Fleetio.",
    "created_at": "Timestamp when the record was created.",
    "updated_at": "Timestamp when the record was last updated.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "vehicles": {
        "description": "An asset tracked in Fleetio — typically a vehicle or piece of equipment, with its identifying and status details.",
        "docs_url": "https://developer.fleetio.com/docs/api/vehicles",
        "columns": {
            **_COMMON_COLUMNS,
            "name": "Display name of the vehicle.",
            "vin": "Vehicle Identification Number.",
            "make": "Manufacturer of the vehicle.",
            "model": "Model of the vehicle.",
            "year": "Model year of the vehicle.",
            "license_plate": "License plate number.",
            "vehicle_status_name": "Current operational status of the vehicle (e.g. Active, In Shop).",
            "vehicle_type_name": "The vehicle's type/classification.",
            "current_meter_value": "Most recent primary meter reading (e.g. odometer).",
            "secondary_meter_value": "Most recent secondary meter reading (e.g. engine hours).",
            "group_name": "Name of the group the vehicle belongs to.",
            "archived_at": "Timestamp when the vehicle was archived, if applicable.",
        },
    },
    "contacts": {
        "description": "A person in Fleetio — an operator, technician, or other contact who can be assigned to vehicles, work orders, and issues.",
        "docs_url": "https://developer.fleetio.com/docs/api/contacts",
        "columns": {
            **_COMMON_COLUMNS,
            "name": "Full name of the contact.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "email": "Contact's email address.",
            "group_name": "Name of the group the contact belongs to.",
            "employee": "Whether the contact is an employee.",
            "technician": "Whether the contact is a technician.",
            "archived_at": "Timestamp when the contact was archived, if applicable.",
        },
    },
    "fuel_entries": {
        "description": "A record of fuel purchased or used for a vehicle, including volume, cost, and the meter reading at fill-up.",
        "docs_url": "https://developer.fleetio.com/docs/api/fuel-entries",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the vehicle this fuel entry belongs to.",
            "date": "Date and time of the fuel entry.",
            "raw_usage": "Volume of fuel added (in the account's fuel units).",
            "us_gallons": "Volume of fuel added, normalized to US gallons.",
            "total_amount": "Total cost of the fuel entry.",
            "cost_per_unit": "Cost per unit of fuel.",
            "usage_in_gallons": "Fuel usage expressed in gallons.",
            "meter_entry_value": "Meter reading captured at the time of fueling.",
            "fuel_type_name": "The type of fuel used.",
        },
    },
    "meter_entries": {
        "description": "A meter reading for a vehicle (e.g. odometer mileage or engine hours) recorded at a point in time.",
        "docs_url": "https://developer.fleetio.com/docs/api/meter-entries",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the vehicle this meter entry belongs to.",
            "value": "The recorded meter value.",
            "date": "Date the meter reading was taken.",
            "meter_type": "Whether the reading is the primary or secondary meter.",
            "void": "Whether the meter entry has been voided.",
            "auto_voided_at": "Timestamp when the entry was automatically voided, if applicable.",
        },
    },
    "service_entries": {
        "description": "A record of maintenance or service performed on a vehicle, including the service tasks completed and their cost.",
        "docs_url": "https://developer.fleetio.com/docs/api/service-entries",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the vehicle that was serviced.",
            "completed_at": "Timestamp when the service was completed.",
            "started_at": "Timestamp when the service started.",
            "total_amount_cents": "Total cost of the service entry, in cents.",
            "labor_cost_cents": "Labor cost portion, in cents.",
            "parts_cost_cents": "Parts cost portion, in cents.",
            "meter_entry_value": "Meter reading captured at the time of service.",
            "vendor_name": "Name of the vendor that performed the service.",
        },
    },
    "work_orders": {
        "description": "A work order in Fleetio that groups the issues, service tasks, parts, and labor needed to maintain a vehicle.",
        "docs_url": "https://developer.fleetio.com/docs/api/work-orders",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the vehicle the work order is for.",
            "number": "Human-readable work order number.",
            "status_name": "Current status of the work order (e.g. Open, Completed).",
            "issued_at": "Timestamp when the work order was issued.",
            "started_at": "Timestamp when work started.",
            "completed_at": "Timestamp when the work order was completed.",
            "total_amount_cents": "Total cost of the work order, in cents.",
            "vehicle_meter_value": "Meter reading captured for the work order.",
        },
    },
    "issues": {
        "description": "A reported problem or fault for a vehicle that may require service, optionally linked to a work order.",
        "docs_url": "https://developer.fleetio.com/docs/api/issues",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the vehicle the issue was reported for.",
            "number": "Human-readable issue number.",
            "summary": "Short summary of the issue.",
            "description": "Detailed description of the issue.",
            "state": "Current state of the issue (e.g. open, resolved, closed).",
            "reported_at": "Timestamp when the issue was reported.",
            "resolved_at": "Timestamp when the issue was resolved, if applicable.",
            "due_date": "Date the issue is due to be addressed.",
            "reported_by_name": "Name of the contact who reported the issue.",
        },
    },
    "parts": {
        "description": "An inventory part in Fleetio used in service entries and work orders, with cost and stocking details.",
        "docs_url": "https://developer.fleetio.com/docs/api/parts",
        "columns": {
            **_COMMON_COLUMNS,
            "number": "Part number.",
            "description": "Description of the part.",
            "manufacturer_part_number": "The manufacturer's part number.",
            "unit_cost_cents": "Cost per unit of the part, in cents.",
            "part_category_name": "Category the part belongs to.",
            "measurement_unit_name": "Unit of measure for the part.",
            "archived_at": "Timestamp when the part was archived, if applicable.",
        },
    },
    "vehicle_assignments": {
        "description": "A record linking a contact (operator) to a vehicle for a period of time.",
        "docs_url": "https://developer.fleetio.com/docs/api/vehicle-assignments",
        "columns": {
            **_COMMON_COLUMNS,
            "vehicle_id": "Identifier of the assigned vehicle.",
            "contact_id": "Identifier of the contact assigned to the vehicle.",
            "started_at": "Timestamp when the assignment started.",
            "ended_at": "Timestamp when the assignment ended, if applicable.",
            "current": "Whether this is the vehicle's current assignment.",
            "comments_count": "Number of comments on the assignment.",
        },
    },
}
