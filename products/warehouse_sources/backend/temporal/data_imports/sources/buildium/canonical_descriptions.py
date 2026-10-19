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
    "bank_accounts": {
        "description": "Bank accounts that hold property, company, and association funds.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiBankAccounts_GetAllBankAccounts",
        "columns": {
            "Id": "Identifier for this bank account.",
            "GLAccount": "General ledger account linked to the bank account.",
            "BankAccountType": "Type of bank account, such as Checking or Savings.",
            "Balance": "Current bank account balance.",
            "IsActive": "Whether the bank account is active.",
        },
    },
    "general_ledger_transactions": {
        "description": "Financial transactions recorded in the general ledger, with their journal lines.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiGeneralLedgerTransactions_GetAllTransactions",
        "columns": {
            "Id": "Identifier for this transaction.",
            "Date": "Date of the transaction.",
            "TransactionType": "Type of transaction that occurred.",
            "TotalAmount": "Sum of all journal line amounts in the transaction.",
            "Journal": "Journal lines that record the transaction against general ledger accounts.",
            "LastUpdatedDateTime": "Time of the most recent transaction update.",
        },
    },
    "lease_transactions": {
        "description": "Charges, payments, credits, and other transactions on each lease ledger.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiLeaseLedgerTransactions_GetLeaseLedgers",
        "columns": {
            "_leases_Id": "Lease whose ledger was read to return the transaction.",
            "Id": "Identifier for this transaction.",
            "Date": "Date of the transaction.",
            "TransactionType": "Type of transaction that occurred.",
            "TotalAmount": "Sum of all journal line amounts in the transaction.",
            "PayeeTenantId": "Tenant associated with the transaction, where applicable.",
        },
    },
    "lease_outstanding_balances": {
        "description": "Leases that have an outstanding balance, split by how long the amount has been due.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiLeaseOutstandingBalances_GetLeaseOutstandingBalances",
        "columns": {
            "LeaseId": "Lease that has the outstanding balance.",
            "PropertyId": "Property covered by the lease.",
            "UnitId": "Unit covered by the lease.",
            "TotalBalance": "Total outstanding balance due.",
            "BalanceOver90Days": "Outstanding balance due from over 90 days ago.",
        },
    },
    "inventory_assets": {
        "description": "Inventory items and assets tracked for properties, units, and the company.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiInventoryAsset_GetInventoryAssets",
        "columns": {
            "Id": "Identifier for this inventory asset.",
            "CategoryId": "Asset category of the item.",
            "PropertyId": "Property associated with the asset, where applicable.",
            "UnitId": "Unit associated with the asset, where applicable.",
            "InventoryStorageId": "Inventory storage location of the asset, where applicable.",
            "WarrantyEndDate": "Date the warranty expires, where applicable.",
            "Quantity": "Quantity of the asset.",
        },
    },
    "inventory_storages": {
        "description": "Storage locations that hold inventory assets.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiInventoryStorage_GetInventoryStorages",
        "columns": {
            "Id": "Identifier for this inventory storage.",
            "Name": "Name of the inventory storage.",
        },
    },
    "asset_categories": {
        "description": "Categories used to group inventory assets.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiAssetCategory_GetAllAssetCategories",
        "columns": {
            "Id": "Identifier for this asset category.",
            "Name": "Name of the asset category.",
        },
    },
    "custom_field_definitions": {
        "description": "Custom fields defined for each Buildium entity type, such as rentals, leases, and vendors.",
        "docs_url": "https://developer.buildium.com/#operation/ExternalApiCustomFieldsDefinitions_GetDefinitionsByEntityType",
        "columns": {
            "Id": "Identifier for this custom field definition.",
            "GroupId": "Custom field group that contains the definition.",
            "EntityTypeName": "Entity type the custom field applies to.",
            "Configuration": "Field type and settings of the custom field.",
        },
    },
}
