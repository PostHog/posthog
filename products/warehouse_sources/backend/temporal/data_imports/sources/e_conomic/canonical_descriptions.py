"""Canonical, documentation-sourced descriptions for Visma e-conomic endpoints and columns.

Sourced from the official e-conomic REST API reference (https://restdocs.e-conomic.com). Keyed by the
endpoint names in `settings.py` `E_CONOMIC_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A debtor (customer) you sell to. Holds billing details, payment terms and the customer's running balance.",
        "docs_url": "https://restdocs.e-conomic.com/#get-customers",
        "columns": {
            "customerNumber": "Unique identifier of the customer.",
            "name": "Customer name.",
            "currency": "The customer's default currency (ISO 4217 code).",
            "paymentTerms": "Default payment terms applied to the customer's invoices.",
            "customerGroup": "The customer group this customer belongs to.",
            "address": "Street address.",
            "city": "City.",
            "zip": "Postal code.",
            "country": "Country.",
            "email": "Primary email address.",
            "balance": "The customer's current outstanding balance in the base currency.",
            "dueAmount": "Amount currently overdue.",
            "vatZone": "VAT zone determining how VAT is calculated for the customer.",
            "lastUpdated": "Timestamp of the last modification to the customer (used for incremental sync).",
        },
    },
    "customer_groups": {
        "description": "A grouping of customers, typically used to assign a common sales account.",
        "docs_url": "https://restdocs.e-conomic.com/#get-customer-groups",
        "columns": {
            "customerGroupNumber": "Unique identifier of the customer group.",
            "name": "Customer group name.",
            "account": "The sales account customers in this group post to.",
        },
    },
    "products": {
        "description": "A product or service you sell, with pricing and inventory references.",
        "docs_url": "https://restdocs.e-conomic.com/#get-products",
        "columns": {
            "productNumber": "Unique identifier of the product.",
            "name": "Product name.",
            "description": "Product description.",
            "costPrice": "Cost price of the product.",
            "recommendedPrice": "Recommended retail price.",
            "salesPrice": "Default sales price.",
            "barred": "Whether the product is barred from being used on new entries.",
            "productGroup": "The product group this product belongs to.",
            "unit": "Unit the product is sold in.",
            "lastUpdated": "Timestamp of the last modification to the product (used for incremental sync).",
        },
    },
    "product_groups": {
        "description": "A grouping of products that share sales accounts and inventory settings.",
        "docs_url": "https://restdocs.e-conomic.com/#get-product-groups",
        "columns": {
            "productGroupNumber": "Unique identifier of the product group.",
            "name": "Product group name.",
            "salesAccounts": "Sales accounts products in this group post to.",
            "inventoryEnabled": "Whether inventory tracking is enabled for this group.",
        },
    },
    "suppliers": {
        "description": "A creditor (supplier) you buy from, with payment and contact details.",
        "docs_url": "https://restdocs.e-conomic.com/#get-suppliers",
        "columns": {
            "supplierNumber": "Unique identifier of the supplier.",
            "name": "Supplier name.",
            "currency": "The supplier's default currency (ISO 4217 code).",
            "paymentTerms": "Default payment terms for the supplier.",
            "supplierGroup": "The supplier group this supplier belongs to.",
            "vatZone": "VAT zone determining how VAT is calculated for the supplier.",
            "email": "Primary email address.",
            "address": "Street address.",
            "city": "City.",
            "zip": "Postal code.",
            "country": "Country.",
            "costAccount": "The default cost account purchases from this supplier post to.",
        },
    },
    "supplier_groups": {
        "description": "A grouping of suppliers, used to assign a common cost account.",
        "docs_url": "https://restdocs.e-conomic.com/#get-supplier-groups",
        "columns": {
            "supplierGroupNumber": "Unique identifier of the supplier group.",
            "name": "Supplier group name.",
            "account": "The account suppliers in this group post to.",
        },
    },
    "accounts": {
        "description": "An account in the chart of accounts, including its type and current balance.",
        "docs_url": "https://restdocs.e-conomic.com/#get-accounts",
        "columns": {
            "accountNumber": "Unique account number in the chart of accounts.",
            "name": "Account name.",
            "accountType": "Type of account (e.g. profitAndLoss, status, heading, totalFrom).",
            "balance": "Current balance of the account.",
            "debitCredit": "Whether the account is a debit or credit account.",
            "blockDirectEntries": "Whether direct entries to the account are blocked.",
        },
    },
    "accounting_years": {
        "description": "A financial (accounting) year and the date range it covers.",
        "docs_url": "https://restdocs.e-conomic.com/#get-accounting-years",
        "columns": {
            "year": "The accounting year identifier (e.g. 2024 or 2024/2025).",
            "fromDate": "First day of the accounting year.",
            "toDate": "Last day of the accounting year.",
        },
    },
    "journals": {
        "description": "A journal used for grouping and posting entries.",
        "docs_url": "https://restdocs.e-conomic.com/#get-journals",
        "columns": {
            "journalNumber": "Unique identifier of the journal.",
            "name": "Journal name.",
            "settings": "Posting settings for the journal.",
        },
    },
    "currencies": {
        "description": "A currency available in the agreement.",
        "docs_url": "https://restdocs.e-conomic.com/#get-currencies",
        "columns": {
            "code": "ISO 4217 currency code (e.g. DKK, EUR, USD).",
            "name": "Currency name.",
            "isoNumber": "ISO 4217 numeric currency code.",
        },
    },
    "payment_terms": {
        "description": "A set of payment terms (credit days and type) applied to invoices.",
        "docs_url": "https://restdocs.e-conomic.com/#get-payment-terms",
        "columns": {
            "paymentTermsNumber": "Unique identifier of the payment terms.",
            "name": "Payment terms name.",
            "daysOfCredit": "Number of days of credit granted.",
            "paymentTermsType": "Type of payment terms (e.g. net, invoiceMonth, paidInCash).",
            "description": "Description of the payment terms.",
        },
    },
    "departments": {
        "description": "A department used to tag entries for dimensional reporting.",
        "docs_url": "https://restdocs.e-conomic.com/#get-departments",
        "columns": {
            "departmentNumber": "Unique identifier of the department.",
            "name": "Department name.",
        },
    },
    "departmental_distributions": {
        "description": "A rule for distributing an entry across multiple departments.",
        "docs_url": "https://restdocs.e-conomic.com/#get-departmental-distributions",
        "columns": {
            "departmentalDistributionNumber": "Unique identifier of the departmental distribution.",
            "name": "Distribution name.",
            "distributionType": "How the amount is distributed across departments.",
            "barred": "Whether the distribution is barred from new entries.",
        },
    },
    "units": {
        "description": "A unit of measure that products can be sold in (e.g. hours, pieces).",
        "docs_url": "https://restdocs.e-conomic.com/#get-units",
        "columns": {
            "unitNumber": "Unique identifier of the unit.",
            "name": "Unit name.",
        },
    },
    "vat_zones": {
        "description": "A VAT zone determining how VAT is applied to customers and suppliers.",
        "docs_url": "https://restdocs.e-conomic.com/#get-vat-zones",
        "columns": {
            "vatZoneNumber": "Unique identifier of the VAT zone.",
            "name": "VAT zone name.",
            "enabledForCustomer": "Whether the zone can be assigned to customers.",
            "enabledForSupplier": "Whether the zone can be assigned to suppliers.",
        },
    },
    "employees": {
        "description": "An employee in the agreement, used as a sales person on invoices.",
        "docs_url": "https://restdocs.e-conomic.com/#get-employees",
        "columns": {
            "employeeNumber": "Unique identifier of the employee.",
            "name": "Employee name.",
            "employeeGroup": "The employee group this employee belongs to.",
            "email": "Employee email address.",
            "phone": "Employee phone number.",
        },
    },
    "invoices_booked": {
        "description": "A booked (finalized, immutable) sales invoice with its amounts and customer reference.",
        "docs_url": "https://restdocs.e-conomic.com/#get-invoices-booked",
        "columns": {
            "bookedInvoiceNumber": "Sequential identifier of the booked invoice (monotonic; used for incremental sync).",
            "orderNumber": "Associated order number, if any.",
            "date": "Booking date of the invoice.",
            "dueDate": "Date the invoice is due for payment.",
            "currency": "Invoice currency (ISO 4217 code).",
            "exchangeRate": "Exchange rate to the base currency at booking time.",
            "netAmount": "Net amount in the invoice currency.",
            "netAmountInBaseCurrency": "Net amount converted to the base currency.",
            "grossAmount": "Gross amount (incl. VAT) in the invoice currency.",
            "grossAmountInBaseCurrency": "Gross amount converted to the base currency.",
            "vatAmount": "Total VAT amount on the invoice.",
            "roundingAmount": "Rounding adjustment applied to the total.",
            "remainder": "Outstanding amount remaining on the invoice.",
            "customer": "The customer the invoice was issued to.",
            "paymentTerms": "Payment terms applied to the invoice.",
        },
    },
    "invoices_drafts": {
        "description": "A draft (not yet booked, editable) sales invoice.",
        "docs_url": "https://restdocs.e-conomic.com/#get-invoices-drafts",
        "columns": {
            "draftInvoiceNumber": "Unique identifier of the draft invoice.",
            "date": "Invoice date.",
            "dueDate": "Date the invoice would be due for payment.",
            "currency": "Invoice currency (ISO 4217 code).",
            "exchangeRate": "Exchange rate to the base currency.",
            "netAmount": "Net amount in the invoice currency.",
            "netAmountInBaseCurrency": "Net amount converted to the base currency.",
            "grossAmount": "Gross amount (incl. VAT) in the invoice currency.",
            "grossAmountInBaseCurrency": "Gross amount converted to the base currency.",
            "vatAmount": "Total VAT amount on the invoice.",
            "customer": "The customer the draft is for.",
            "paymentTerms": "Payment terms applied to the draft.",
            "lastUpdated": "Timestamp of the last modification to the draft.",
        },
    },
}
