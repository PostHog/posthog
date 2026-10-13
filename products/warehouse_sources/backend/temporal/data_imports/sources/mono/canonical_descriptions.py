from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "Customers registered with the Mono business.",
        "docs_url": "https://docs.mono.co/api/customer/list-all-customers",
        "columns": {
            "id": "The customer identifier.",
            "name": "The customer's full name.",
            "email": "The customer's email address.",
            "phone": "The customer's phone number.",
            "identification_type": "The type of identification provided by the customer.",
            "identification_no": "The customer's identification number.",
        },
    },
    "accounts": {
        "description": "Bank accounts linked to the Mono business.",
        "docs_url": "https://docs.mono.co/api/bank-data/accounts/get-accounts",
        "columns": {
            "id": "The linked account identifier.",
            "name": "The account holder's name.",
            "account_number": "The bank account number.",
            "currency": "The account currency.",
            "institution": "The financial institution that holds the account.",
            "customer": "The customer associated with the account.",
            "auth_method": "The method used to connect the account.",
        },
    },
    "transactions": {
        "description": "Transactions from linked bank accounts within the selected date range.",
        "docs_url": "https://docs.mono.co/api/bank-data/transactions",
        "columns": {
            "id": "The transaction identifier within the linked account.",
            "account_id": "The linked account identifier added during import.",
            "narration": "The transaction description.",
            "amount": "The transaction amount in the currency's smallest unit, such as kobo, pesewa, or cents.",
            "type": "Whether the transaction is a credit or debit.",
            "date": "The transaction date and time.",
            "category": "The transaction category assigned by Mono.",
        },
    },
}
