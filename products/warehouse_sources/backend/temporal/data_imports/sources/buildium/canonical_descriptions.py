from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "rental_properties": {
        "description": "Properties managed as rentals in Buildium.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiRentals_GetAllRentals",
        "columns": {
            "Id": "Identifier for this property.",
            "Name": "Property name.",
            "NumberUnits": "Number of rental units at the property.",
        },
    },
    "rental_units": {
        "description": "Individual units within rental properties.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiRentalUnits_GetAllRentalUnits",
        "columns": {
            "Id": "Identifier for this unit.",
            "PropertyId": "Property that contains the unit.",
            "MarketRent": "Rent used for listings, separate from the lease rent.",
        },
    },
    "leases": {
        "description": "Rental agreements for property units.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiLeases_GetLeases",
        "columns": {
            "Id": "Identifier for this lease.",
            "UnitId": "Unit covered by the lease.",
            "PropertyId": "Property covered by the lease.",
            "LastUpdatedDateTime": "Time of the most recent lease update.",
        },
    },
    "tenants": {
        "description": "Tenants associated with rental leases.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiRentalTenants_GetAllTenants",
        "columns": {
            "Id": "Identifier for this tenant.",
            "Leases": "Leases associated with the tenant, including past leases.",
        },
    },
    "rental_owners": {
        "description": "Owners of managed rental properties.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiRentalOwners_GetRentalOwners",
        "columns": {"Id": "Identifier for this owner.", "PropertyIds": "Properties associated with the owner."},
    },
    "vendors": {
        "description": "Vendors that provide services for managed properties.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiVendors_GetAllVendors",
        "columns": {"Id": "Identifier for this vendor.", "IsActive": "Whether the vendor is active."},
    },
    "bills": {
        "description": "Bills recorded in Buildium accounting.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiBills_GetBillsAsync",
        "columns": {"Id": "Identifier for this bill.", "Date": "Date assigned to the bill."},
    },
    "general_ledger_accounts": {
        "description": "Accounts that classify accounting transactions.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiGeneralLedgerAccounts_GetAllGLAccounts",
        "columns": {"Id": "Identifier for this ledger account.", "Name": "Name assigned to the account."},
    },
    "work_orders": {
        "description": "Work orders for property maintenance.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiWorkOrders_GetAllWorkOrders",
        "columns": {
            "Id": "Identifier for this work order.",
            "VendorId": "Vendor assigned to the work.",
            "Amount": "Total cost of the work order.",
        },
    },
    "applicants": {
        "description": "Applicants for rental properties and units.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiApplicants_GetApplicants",
        "columns": {
            "Id": "Identifier for this applicant.",
            "PropertyId": "Property associated with the applicant.",
            "LastUpdatedDateTime": "Time of the most recent applicant update.",
        },
    },
}
