from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "databases": {
        "description": "Databases belonging to the configured Turso organization.",
        "docs_url": "https://docs.turso.tech/api-reference/databases/list",
        "columns": {
            "DbId": "Unique database identifier.",
            "Name": "Database name, unique within the organization.",
            "Hostname": "Hostname used for database connections.",
            "group": "Group containing the database.",
            "block_reads": "Whether reads are blocked.",
            "block_writes": "Whether writes are blocked.",
        },
    },
    "groups": {
        "description": "Groups of databases within the organization.",
        "docs_url": "https://docs.turso.tech/api-reference/groups/list",
        "columns": {"uuid": "Unique group identifier.", "name": "Group name.", "primary": "Primary location code."},
    },
    "members": {
        "description": "Organization members and their access roles.",
        "docs_url": "https://docs.turso.tech/api-reference/organizations/members/list",
        "columns": {
            "username": "Member username.",
            "email": "Member email address.",
            "role": "Organization access role.",
        },
    },
    "invites": {
        "description": "Pending invitations to join the organization.",
        "docs_url": "https://docs.turso.tech/api-reference/organizations/invites/list-v2",
        "columns": {
            "id": "Unique invitation identifier.",
            "email": "Invited email address.",
            "role": "Role assigned to the invited member.",
            "created_at": "Time the invitation was created.",
        },
    },
    "invoices": {
        "description": "Issued organization invoices.",
        "docs_url": "https://docs.turso.tech/api-reference/organizations/invoices",
        "columns": {
            "invoice_number": "Unique invoice number.",
            "amount_due": "Formatted invoice amount in US dollars.",
            "due_date": "Invoice payment due date.",
            "paid_at": "Time the invoice was paid.",
        },
    },
    "audit_logs": {
        "description": "Actions performed within the organization, available on the Scaler plan and higher.",
        "docs_url": "https://docs.turso.tech/api-reference/audit-logs/list",
        "columns": {
            "code": "Action code.",
            "author": "Username of the person who performed the action.",
            "created_at": "Time the action occurred.",
            "data": "Action payload.",
        },
    },
    "database_usage": {
        "description": "Current calendar month usage for each database, including totals and instance metrics.",
        "docs_url": "https://docs.turso.tech/api-reference/databases/usage",
        "columns": {
            "database_id": "Unique identifier from the parent database listing.",
            "database_name": "Name from the parent database listing.",
            "total": "Database totals for rows read, rows written, storage bytes, and bytes synced.",
            "instances": "Usage metrics for individual database instances.",
        },
    },
}
