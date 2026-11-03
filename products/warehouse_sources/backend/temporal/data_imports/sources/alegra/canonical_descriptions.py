from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "invoices": {
        "description": "Sales invoices with line items, taxes, payments, and outstanding balances.",
        "docs_url": "https://developer.alegra.com/reference/get_invoices",
        "columns": {
            "id": "Unique identifier of the sales invoice.",
            "date": "Invoice document date.",
            "dueDate": "Invoice payment due date.",
            "total": "Total invoice amount.",
            "totalPaid": "Amount paid against the invoice.",
            "balance": "Outstanding invoice balance.",
        },
    },
    "contacts": {
        "description": "Customers and suppliers with contact details and accounting information.",
        "docs_url": "https://developer.alegra.com/reference/listcontacts-1",
        "columns": {
            "id": "Unique identifier of the contact.",
            "type": "Contact roles: client, provider, or both.",
            "identification": "Tax or personal identification number of the contact.",
        },
    },
    "items": {
        "description": "Products and services with prices, taxes, and inventory details.",
        "docs_url": "https://developer.alegra.com/reference/get_items",
        "columns": {
            "id": "Unique identifier of the product or service.",
            "reference": "Product or service reference.",
            "inventory": "Inventory quantities, units, costs, and warehouses.",
        },
    },
    "incoming_payments": {
        "description": "Received payments and their associated invoices, contacts, and bank accounts.",
        "docs_url": "https://developer.alegra.com/reference/get_payments-1",
        "columns": {"id": "Unique identifier of the payment.", "date": "Payment document date."},
    },
    "outgoing_payments": {
        "description": "Outgoing payments and their associated purchase documents and bank accounts.",
        "docs_url": "https://developer.alegra.com/reference/get_payments-1",
        "columns": {"id": "Unique identifier of the payment.", "date": "Payment document date."},
    },
    "bills": {
        "description": "Supplier bills with purchase details, taxes, payments, and outstanding balances.",
        "docs_url": "https://developer.alegra.com/reference/get_bills",
        "columns": {
            "id": "Unique identifier of the supplier bill.",
            "date": "Supplier bill document date.",
            "provider": "Supplier associated with the bill.",
        },
    },
    "estimates": {
        "description": "Sales quotations with customers, line items, prices, and taxes.",
        "docs_url": "https://developer.alegra.com/reference/get_estimates",
        "columns": {"id": "Unique identifier of the quotation.", "date": "Quotation document date."},
    },
    "credit_notes": {
        "description": "Customer credit notes, associated sales invoices, and refunds.",
        "docs_url": "https://developer.alegra.com/reference/get_credit-notes",
        "columns": {"id": "Unique identifier of the credit note.", "date": "Credit note document date."},
    },
    "debit_notes": {
        "description": "Supplier debit notes and their associated purchase documents.",
        "docs_url": "https://developer.alegra.com/reference/get_debit-notes",
        "columns": {"id": "Unique identifier of the debit note.", "date": "Debit note document date."},
    },
    "bank_accounts": {
        "description": "Bank, cash, and credit card accounts used to receive and make payments.",
        "docs_url": "https://developer.alegra.com/reference/listbankaccounts",
        "columns": {
            "id": "Unique identifier of the bank account.",
            "type": "Account type, such as bank, credit-card, or cash.",
            "status": "Account status: active or inactive.",
            "initialBalance": "Opening balance of the account.",
            "initialBalanceDate": "Date of the opening balance.",
        },
    },
    "item_categories": {
        "description": "Categories used to group products and services.",
        "docs_url": "https://developer.alegra.com/reference/get_item-categories",
        "columns": {
            "id": "Unique identifier of the item category.",
            "status": "Category status: active or inactive.",
        },
    },
    "warehouses": {
        "description": "Warehouses that hold item inventory.",
        "docs_url": "https://developer.alegra.com/reference/get_warehouses",
        "columns": {
            "id": "Unique identifier of the warehouse.",
            "isDefault": "Whether this is the company's default warehouse.",
            "status": "Warehouse status: active or inactive.",
        },
    },
    "inventory_adjustments": {
        "description": "Manual stock corrections that add or remove item quantities in a warehouse.",
        "docs_url": "https://developer.alegra.com/reference/get_inventory-adjustments",
        "columns": {
            "id": "Unique identifier of the inventory adjustment.",
            "date": "Inventory adjustment document date.",
            "warehouse": "Warehouse where the adjustment applies.",
            "items": "Adjusted items with quantity, direction (in or out), and unit cost.",
        },
    },
    "warehouse_transfers": {
        "description": "Stock movements of items from one warehouse to another.",
        "docs_url": "https://developer.alegra.com/reference/transferencia-de-bodegas",
        "columns": {
            "id": "Unique identifier of the warehouse transfer.",
            "date": "Warehouse transfer document date.",
            "origin": "Warehouse that the items leave.",
            "destination": "Warehouse that receives the items.",
            "items": "Transferred items with their quantities.",
        },
    },
    "purchase_orders": {
        "description": "Purchase orders sent to suppliers before the supplier bills arrive.",
        "docs_url": "https://developer.alegra.com/reference/listpurchaseorders",
        "columns": {
            "id": "Unique identifier of the purchase order.",
            "date": "Purchase order document date.",
            "dueDate": "Purchase order due date.",
            "deliveryDate": "Expected delivery date of the order.",
            "status": "Purchase order status: open, close, or void.",
            "provider": "Supplier of the purchase order.",
            "purchases": "Ordered items and expense categories with price, quantity, discount, and tax.",
        },
    },
    "recurring_invoices": {
        "description": "Schedules that create sales invoices for a client at a fixed interval.",
        "docs_url": "https://developer.alegra.com/reference/facturas-recurrentes",
        "columns": {
            "id": "Unique identifier of the recurring invoice.",
            "startDate": "Date of the first invoice in the schedule.",
            "endDate": "Date of the last invoice in the schedule, or null when the schedule has no end.",
            "repeatEvery": "Interval in months between generated invoices.",
            "client": "Client that receives the generated invoices.",
            "total": "Total amount of each generated invoice.",
            "nextCreation": "Time when Alegra creates the next invoice.",
            "lastCreation": "Time when Alegra created the most recent invoice.",
        },
    },
    "taxes": {
        "description": "Tax definitions and rates that apply to invoices, bills, and items.",
        "docs_url": "https://developer.alegra.com/reference/impuestos",
        "columns": {
            "id": "Unique identifier of the tax.",
            "name": "Name of the tax.",
            "percentage": "Tax rate as a percentage.",
            "type": "Tax type, such as IVA.",
            "status": "Tax status: active or inactive.",
        },
    },
}
