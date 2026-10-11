from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "account": {
        "description": "A general ledger account in the chart of accounts.",
        "columns": {
            "id": "Internal ID of the account.",
            "acctnumber": "Account number.",
            "accttype": "Account type, such as Bank, Income, or Expense.",
            "fullname": "Full hierarchical name of the account.",
        },
    },
    "accountingperiod": {
        "description": "A fiscal period (year, quarter, or month) used for posting and closing.",
        "columns": {
            "id": "Internal ID of the accounting period.",
            "periodname": "Name of the period.",
            "startdate": "First day of the period.",
            "enddate": "Last day of the period.",
            "closed": "Whether the period is closed.",
        },
    },
    "classification": {
        "description": "A class, a segment that categorizes transactions and records.",
        "columns": {
            "id": "Internal ID of the class.",
            "name": "Name of the class.",
        },
    },
    "contact": {
        "description": "A person associated with a customer, vendor, or partner.",
        "columns": {
            "id": "Internal ID of the contact.",
            "company": "Internal ID of the company the contact belongs to.",
            "email": "Email address of the contact.",
            "lastmodifieddate": "When the contact was last modified, in UTC.",
        },
    },
    "currency": {
        "description": "A currency enabled in the account, with its exchange rate settings.",
        "columns": {
            "id": "Internal ID of the currency.",
            "symbol": "ISO currency code.",
            "name": "Name of the currency.",
        },
    },
    "customer": {
        "description": "A customer, either a company or an individual.",
        "columns": {
            "id": "Internal ID of the customer.",
            "entityid": "Customer ID shown in NetSuite.",
            "companyname": "Company name of the customer.",
            "email": "Email address of the customer.",
            "datecreated": "When the customer record was created.",
            "lastmodifieddate": "When the customer was last modified, in UTC.",
        },
    },
    "department": {
        "description": "A department, a segment that categorizes transactions and records.",
        "columns": {
            "id": "Internal ID of the department.",
            "name": "Name of the department.",
        },
    },
    "employee": {
        "description": "An employee record.",
        "columns": {
            "id": "Internal ID of the employee.",
            "entityid": "Employee ID shown in NetSuite.",
            "email": "Email address of the employee.",
            "lastmodifieddate": "When the employee was last modified, in UTC.",
        },
    },
    "item": {
        "description": "An item that the company buys or sells, such as inventory, a service, or a discount.",
        "columns": {
            "id": "Internal ID of the item.",
            "itemid": "Item name or number.",
            "itemtype": "Item type, such as InvtPart or Service.",
            "lastmodifieddate": "When the item was last modified, in UTC.",
        },
    },
    "location": {
        "description": "A location, such as a warehouse or store, used to track inventory and transactions.",
        "columns": {
            "id": "Internal ID of the location.",
            "name": "Name of the location.",
        },
    },
    "subsidiary": {
        "description": "A subsidiary in a OneWorld account hierarchy.",
        "columns": {
            "id": "Internal ID of the subsidiary.",
            "name": "Name of the subsidiary.",
            "currency": "Internal ID of the base currency of the subsidiary.",
        },
    },
    "transaction": {
        "description": "The header of a transaction, such as a sales order, invoice, bill, payment, or journal entry.",
        "columns": {
            "id": "Internal ID of the transaction.",
            "tranid": "Document number of the transaction.",
            "type": "Transaction type code, such as SalesOrd, CustInvc, or Journal.",
            "trandate": "Transaction date.",
            "entity": "Internal ID of the customer, vendor, or other entity on the transaction.",
            "status": "Status code of the transaction.",
            "foreigntotal": "Total amount in the transaction currency.",
            "lastmodifieddate": "When the transaction was last modified, in UTC.",
        },
    },
    "transactionaccountingline": {
        "description": "The general ledger impact of a transaction line, for each accounting book.",
        "columns": {
            "transaction": "Internal ID of the transaction.",
            "transactionline": "ID of the transaction line.",
            "accountingbook": "Internal ID of the accounting book.",
            "account": "Internal ID of the posting account.",
            "amount": "Posted amount in the base currency.",
            "debit": "Debit amount.",
            "credit": "Credit amount.",
            "posting": "Whether the line posts to the general ledger.",
        },
    },
    "transactionline": {
        "description": "A line on a transaction, such as an item line or an expense line.",
        "columns": {
            "transaction": "Internal ID of the transaction the line belongs to.",
            "id": "ID of the line, unique within its transaction.",
            "item": "Internal ID of the item on the line.",
            "quantity": "Quantity on the line.",
            "rate": "Unit rate on the line.",
            "foreignamount": "Line amount in the transaction currency.",
            "mainline": "Whether this is the header line of the transaction.",
        },
    },
    "vendor": {
        "description": "A vendor (supplier) the company buys from.",
        "columns": {
            "id": "Internal ID of the vendor.",
            "entityid": "Vendor ID shown in NetSuite.",
            "companyname": "Company name of the vendor.",
            "email": "Email address of the vendor.",
            "lastmodifieddate": "When the vendor was last modified, in UTC.",
        },
    },
}
