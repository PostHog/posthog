from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the Upstash Developer API reference
# (https://upstash.com/docs/devops/developer-api). Keyed by the endpoint/schema name from
# get_schemas / ENDPOINTS; any column not covered here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "redis_databases": {
        "description": "Every Upstash Redis database on the account, with its configuration, plan, region, and state.",
        "docs_url": "https://upstash.com/docs/devops/developer-api/redis/list_databases",
        "columns": {
            "database_id": "Unique identifier of the database.",
            "database_name": "Name of the database.",
            "region": "Region the database is deployed in (global for global databases).",
            "type": "Plan of the database (free, payg, pro, or paid).",
            "port": "Port the database listens on.",
            "creation_time": "Creation time of the database as Unix time (seconds).",
            "state": "State of the database (active, suspended, or passive).",
            "endpoint": "Endpoint hostname used to connect to the database.",
            "tls": "Whether TLS/SSL is enabled.",
            "eviction": "Whether key eviction is enabled.",
            "auto_upgrade": "Whether auto-upgrade is enabled.",
            "consistent": "Whether strong consistency mode is enabled.",
            "primary_region": "Primary region for the database.",
            "read_regions": "Read replica regions for the database.",
            "db_resource_size": "Provisioned resource size (S, M, L, XL, XXL, or 3XL).",
            "daily_backup_enabled": "Whether daily backups are enabled.",
        },
    },
    "redis_stats": {
        "description": "Usage and billing statistics for each Redis database: daily and monthly commands, bandwidth, storage, latency percentiles, and cache hit/miss counts. One row per database.",
        "docs_url": "https://upstash.com/docs/devops/developer-api/redis/get_database_stats",
        "columns": {
            "database_id": "Identifier of the database these stats belong to.",
            "daily_net_commands": "Total commands run in the last day.",
            "daily_read_requests": "Read requests in the last day.",
            "daily_write_requests": "Write requests in the last day.",
            "dailybandwidth": "Bandwidth used in the last day, in bytes.",
            "total_monthly_billing": "Total billing for the current month.",
            "total_monthly_bandwidth": "Total bandwidth used this month, in bytes.",
            "total_monthly_requests": "Total requests this month.",
            "total_monthly_storage": "Total storage used this month, in bytes.",
            "current_storage": "Current storage used, in bytes.",
            "dailybilling": "Daily billing as a time series of {x, y} points.",
            "dailyrequests": "Daily requests as a time series of {x, y} points.",
            "bandwidths": "Bandwidth as a time series of {x, y} points.",
        },
    },
    "teams": {
        "description": "Teams the account belongs to.",
        "docs_url": "https://upstash.com/docs/devops/developer-api/teams/list_teams",
        "columns": {
            "team_id": "Unique identifier of the team.",
            "team_name": "Name of the team.",
            "copy_cc": "Whether credit card information was copied to the team on creation.",
        },
    },
    "vector_indexes": {
        "description": "Upstash Vector indexes on the account, with their configuration, plan, and per-plan limits.",
        "docs_url": "https://upstash.com/docs/devops/developer-api/vector/list_indices",
        "columns": {
            "id": "Unique identifier of the vector index.",
            "customer_id": "Owner of the index.",
            "name": "Name of the index.",
            "similarity_function": "Similarity function used (COSINE, EUCLIDEAN, or DOT_PRODUCT).",
            "dimension_count": "Number of dimensions per vector.",
            "embedding_model": "Predefined text embedding model, if configured.",
            "index_type": "Index type (DENSE, SPARSE, or HYBRID).",
            "type": "Plan of the index (free, payg, or fixed).",
            "region": "Region the index is deployed in.",
            "endpoint": "REST endpoint of the index.",
            "creation_time": "Creation time of the index as Unix time (seconds).",
        },
    },
    "audit_logs": {
        "description": "Chronological record of actions taken on the account and its databases (creations, deletions, config changes), with the actor and originating IP.",
        "docs_url": "https://upstash.com/docs/devops/developer-api/account/list_audit_logs",
        "columns": {
            "log_id": "Unique identifier for the log entry.",
            "customer_id": "ID or email of the associated customer.",
            "actor": "The user or system that performed the action.",
            "timestamp": "Unix timestamp of when the action occurred.",
            "action": "Numeric id representing the specific action type.",
            "action_string": "Human-readable description of the action.",
            "source": "The source method or client used to perform the action.",
            "entity": "The primary entity affected by the action.",
            "ip": "The IP address from which the request originated.",
        },
    },
}
