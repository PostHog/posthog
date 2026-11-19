from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "database_instances": {
        "description": "Primary and replica instances of each database, one per location in the database's group.",
        "docs_url": "https://docs.turso.tech/api-reference/databases/list-instances",
        "columns": {
            "database_id": "Unique identifier from the parent database listing.",
            "database_name": "Name from the parent database listing.",
            "uuid": "Unique instance identifier, as referenced in database usage.",
            "name": "Instance name, which is its location code.",
            "type": "Instance role, either primary or replica.",
            "region": "Location code of the region that hosts the instance.",
            "hostname": "Hostname for libSQL and HTTP connections to this instance only.",
        },
    },
    "database_stats": {
        "description": "Top queries run on each database, with the rows each query read and wrote.",
        "docs_url": "https://docs.turso.tech/api-reference/databases/stats",
        "columns": {
            "database_id": "Unique identifier from the parent database listing.",
            "database_name": "Name from the parent database listing.",
            "query": "SQL statement that was executed.",
            "rows_read": "Number of rows the query read.",
            "rows_written": "Number of rows the query inserted, updated, or deleted.",
        },
    },
    "organization_usage": {
        "description": "Usage for the current billing cycle of the organization, with a breakdown per database.",
        "docs_url": "https://docs.turso.tech/api-reference/organizations/usage",
        "columns": {
            "uuid": "Unique organization identifier.",
            "usage": "Organization totals for rows read, rows written, databases, locations, storage bytes, groups, and bytes synced.",
            "databases": "Usage of each database, with totals and per-instance metrics.",
        },
    },
    "locations": {
        "description": "Locations where databases can be created or replicated.",
        "docs_url": "https://docs.turso.tech/api-reference/locations/list",
        "columns": {
            "code": "Location code, as used in database, group, and instance regions.",
            "name": "Human-readable location name.",
        },
    },
}
