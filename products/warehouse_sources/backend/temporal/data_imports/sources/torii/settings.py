from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.types import IncrementalField

TORII_BASE_URL = "https://api.toriihq.com/v1.0"
# Contracts only gains cursor pagination, search, sort, and filters under API version 1.1 (the
# default for keys created after Aug 1 2026; older keys default to 1.0). Sending the header
# explicitly on every request pins us to the richer, documented behavior regardless of key age.
TORII_API_VERSION = "1.1"

PAGE_SIZE = 500

ENDPOINTS = (
    "Apps",
    "Users",
    "Contracts",
    "Transactions",
)

# Torii's public API reference documents no server-side "updated since" / "created since" filter on
# any of these list endpoints, so every endpoint is full-refresh only (an empty entry means
# full-refresh — see `build_endpoint_schemas`).
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

PRIMARY_KEYS: dict[str, list[str]] = {
    "Apps": ["id"],
    "Users": ["id"],
    "Contracts": ["id"],
    "Transactions": ["id"],
}

# Stable, never-changing datetime field to partition each table on. Contracts has no documented
# creation-timestamp field, so it isn't partitioned.
PARTITION_KEYS: dict[str, str | None] = {
    "Apps": "creationTime",
    "Users": "creationTime",
    "Contracts": None,
    "Transactions": "transactionDate",
}

# Explicit field lists (beyond the API's sparse defaults) for the endpoints whose default response
# omits fields a SaaS-spend/governance use case needs. Only fields confirmed in the public API
# reference are listed.
_APP_FIELDS = (
    "id,name,primaryOwner,appOwners,state,category,url,imageUrl,description,tags,score,"
    "isCustom,addedBy,creationTime,isHidden,sources,vendor,activeUsersCount,lastVisitTime"
)

_CONTRACT_FIELDS = "id,idApp,name,owner,status,createdBy"

_TRANSACTION_FIELDS = (
    "id,idApp,appName,idAppAccount,appAccountName,fileName,transactionDate,amount,source,"
    "description,department,domain,externalAccountId,externalAccountName,mappingStatus,"
    "mappingLogic,reportedByFullName,idExternalTransaction"
)


def get_resource(name: str) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Apps": {
            "name": "Apps",
            "table_name": "apps",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "apps",
                "path": "/apps",
                "params": {
                    "fields": _APP_FIELDS,
                    "size": PAGE_SIZE,
                    "sort": "creationTime:asc",
                },
            },
        },
        "Users": {
            "name": "Users",
            "table_name": "users",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "users",
                "path": "/users",
                "params": {
                    "size": PAGE_SIZE,
                    "sort": "creationTime:asc",
                },
            },
        },
        "Contracts": {
            "name": "Contracts",
            "table_name": "contracts",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "contracts",
                "path": "/contracts",
                "params": {
                    "fields": _CONTRACT_FIELDS,
                    "size": PAGE_SIZE,
                    "sort": "id:asc",
                },
            },
        },
        "Transactions": {
            "name": "Transactions",
            "table_name": "transactions",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "transactions",
                "path": "/transactions",
                "params": {
                    "fields": _TRANSACTION_FIELDS,
                    "size": PAGE_SIZE,
                    "sort": "transactionDate:asc",
                },
            },
        },
    }
    return resources[name]
