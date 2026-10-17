"""Canonical, documentation-sourced descriptions for Xero endpoints and columns.

Sourced from the Xero Accounting API reference (https://developer.xero.com/documentation/api/accounting/overview).
Keyed by the endpoint names in `settings.py`, which match the `ExternalDataSchema.name` of a synced
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://developer.xero.com/documentation/api/accounting"

_UPDATED = {"UpdatedDateUTC": "Time the record was last changed in Xero, in UTC."}

_TRANSACTION_COLUMNS = {
    **_UPDATED,
    "Type": "Kind of transaction, such as ACCREC for a sales document or ACCPAY for a purchase document.",
    "Contact": "The contact the transaction is with.",
    "Date": "Date of the transaction, in the organisation's time zone.",
    "Status": "Status of the transaction, such as DRAFT, AUTHORISED, PAID or VOIDED.",
    "LineAmountTypes": "Whether line amounts are Exclusive, Inclusive or NoTax.",
    "LineItems": "Line items of the transaction.",
    "SubTotal": "Total before tax.",
    "TotalTax": "Total tax.",
    "Total": "Total including tax.",
    "CurrencyCode": "Currency of the transaction.",
    "CurrencyRate": "Exchange rate to the organisation's base currency.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "invoices": {
        "description": "A sales invoice (ACCREC) or a purchase bill (ACCPAY).",
        "docs_url": f"{_DOCS}/invoices",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "InvoiceID": "Unique identifier for the invoice.",
            "InvoiceNumber": "Number of the invoice, unique per organisation for sales invoices.",
            "Reference": "Free-text reference on the invoice.",
            "DueDate": "Date the invoice is due.",
            "AmountDue": "Amount still owed on the invoice.",
            "AmountPaid": "Amount paid on the invoice.",
            "AmountCredited": "Amount covered by credit notes.",
            "FullyPaidOnDate": "Date the invoice was fully paid.",
            "Payments": "Payments applied to the invoice.",
        },
    },
    "credit_notes": {
        "description": "A credit note that reduces what a customer owes (ACCRECCREDIT) or what the organisation owes a supplier (ACCPAYCREDIT).",
        "docs_url": f"{_DOCS}/creditnotes",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "CreditNoteID": "Unique identifier for the credit note.",
            "CreditNoteNumber": "Number of the credit note.",
            "RemainingCredit": "Credit not yet allocated to invoices.",
            "Allocations": "Invoices the credit is allocated to.",
        },
    },
    "payments": {
        "description": "A payment applied to an invoice, credit note, prepayment or overpayment.",
        "docs_url": f"{_DOCS}/payments",
        "columns": {
            **_UPDATED,
            "PaymentID": "Unique identifier for the payment.",
            "Date": "Date of the payment.",
            "Amount": "Amount of the payment in the currency of the invoice.",
            "CurrencyRate": "Exchange rate to the organisation's base currency.",
            "PaymentType": "Kind of payment, such as ACCRECPAYMENT or ACCPAYPAYMENT.",
            "Status": "Status of the payment: AUTHORISED or DELETED.",
            "Reference": "Free-text reference on the payment.",
            "IsReconciled": "Whether the payment is reconciled against a bank statement line.",
            "Account": "Bank account the payment was made to or from.",
            "Invoice": "Invoice the payment applies to.",
        },
    },
    "bank_transactions": {
        "description": "A spend or receive money transaction on a bank account.",
        "docs_url": f"{_DOCS}/banktransactions",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "BankTransactionID": "Unique identifier for the bank transaction.",
            "BankAccount": "Bank account of the transaction.",
            "IsReconciled": "Whether the transaction is reconciled against a bank statement line.",
            "Reference": "Free-text reference on the transaction.",
        },
    },
    "contacts": {
        "description": "A customer or supplier.",
        "docs_url": f"{_DOCS}/contacts",
        "columns": {
            **_UPDATED,
            "ContactID": "Unique identifier for the contact.",
            "ContactNumber": "Identifier of the contact in an external system.",
            "AccountNumber": "Account number the organisation uses for the contact.",
            "ContactStatus": "Status of the contact: ACTIVE, ARCHIVED or GDPRREQUEST.",
            "Name": "Name of the contact or business.",
            "FirstName": "First name of the contact person.",
            "LastName": "Last name of the contact person.",
            "EmailAddress": "Email address of the contact person.",
            "IsSupplier": "Whether the contact has a bill or purchase record.",
            "IsCustomer": "Whether the contact has a sales invoice record.",
            "DefaultCurrency": "Default currency for the contact.",
            "Addresses": "Postal and street addresses of the contact.",
            "Phones": "Phone numbers of the contact.",
        },
    },
    "manual_journals": {
        "description": "A manual journal that adjusts account balances directly.",
        "docs_url": f"{_DOCS}/manualjournals",
        "columns": {
            **_UPDATED,
            "ManualJournalID": "Unique identifier for the manual journal.",
            "Date": "Date of the journal.",
            "Status": "Status of the journal, such as DRAFT, POSTED or VOIDED.",
            "Narration": "Description of the journal.",
            "JournalLines": "Debit and credit lines of the journal.",
        },
    },
    "overpayments": {
        "description": "Money received from a customer or paid to a supplier beyond what an invoice asked for.",
        "docs_url": f"{_DOCS}/overpayments",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "OverpaymentID": "Unique identifier for the overpayment.",
            "RemainingCredit": "Amount of the overpayment not yet allocated.",
            "Allocations": "Invoices the overpayment is allocated to.",
        },
    },
    "prepayments": {
        "description": "Money received from a customer or paid to a supplier before an invoice exists.",
        "docs_url": f"{_DOCS}/prepayments",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "PrepaymentID": "Unique identifier for the prepayment.",
            "RemainingCredit": "Amount of the prepayment not yet allocated.",
            "Allocations": "Invoices the prepayment is allocated to.",
        },
    },
    "purchase_orders": {
        "description": "A purchase order sent to a supplier.",
        "docs_url": f"{_DOCS}/purchaseorders",
        "columns": {
            **_TRANSACTION_COLUMNS,
            "PurchaseOrderID": "Unique identifier for the purchase order.",
            "PurchaseOrderNumber": "Number of the purchase order.",
            "DeliveryDate": "Date the goods are due for delivery.",
            "Reference": "Free-text reference on the purchase order.",
        },
    },
    "accounts": {
        "description": "An account in the organisation's chart of accounts.",
        "docs_url": f"{_DOCS}/accounts",
        "columns": {
            **_UPDATED,
            "AccountID": "Unique identifier for the account.",
            "Code": "Code of the account.",
            "Name": "Name of the account.",
            "Type": "Type of the account, such as BANK, REVENUE or EXPENSE.",
            "Class": "Class of the account: ASSET, EQUITY, EXPENSE, LIABILITY or REVENUE.",
            "Status": "Status of the account: ACTIVE or ARCHIVED.",
            "TaxType": "Default tax type of the account.",
            "BankAccountNumber": "Bank account number, for bank accounts.",
            "CurrencyCode": "Currency of a bank account.",
        },
    },
    "items": {
        "description": "A product or service the organisation buys or sells.",
        "docs_url": f"{_DOCS}/items",
        "columns": {
            **_UPDATED,
            "ItemID": "Unique identifier for the item.",
            "Code": "Code of the item, unique per organisation.",
            "Name": "Name of the item.",
            "Description": "Sales description of the item.",
            "IsSold": "Whether the item appears on sales transactions.",
            "IsPurchased": "Whether the item appears on purchase transactions.",
            "IsTrackedAsInventory": "Whether Xero tracks stock for the item.",
            "QuantityOnHand": "Quantity in stock, for tracked items.",
            "SalesDetails": "Default unit price and account for sales.",
            "PurchaseDetails": "Default unit price and account for purchases.",
        },
    },
    "organisation": {
        "description": "Settings of the connected Xero organisation.",
        "docs_url": f"{_DOCS}/organisation",
        "columns": {
            "OrganisationID": "Unique identifier for the organisation.",
            "Name": "Display name of the organisation.",
            "LegalName": "Legal name of the organisation.",
            "BaseCurrency": "Base currency of the organisation.",
            "CountryCode": "Country of the organisation.",
            "Timezone": "Time zone of the organisation.",
            "FinancialYearEndDay": "Day of the financial year end.",
            "FinancialYearEndMonth": "Month of the financial year end.",
            "OrganisationType": "Type of the organisation, such as COMPANY or SOLETRADER.",
            "CreatedDateUTC": "Time the organisation was created in Xero, in UTC.",
        },
    },
}
