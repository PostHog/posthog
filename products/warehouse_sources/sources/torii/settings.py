from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, EndpointResource, IncrementalField

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
    "AppUsers",
    "Roles",
    "ActionExecutions",
    "FieldsMetadata",
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
    # One row per app account a user holds, so the account is part of the key.
    "AppUsers": ["idApp", "idUser", "idAppAccount"],
    "Roles": ["id"],
    "ActionExecutions": ["id"],
    "FieldsMetadata": ["entity", "systemKey"],
}

# Stable, never-changing datetime field to partition each table on. Contracts has no documented
# creation-timestamp field, so it isn't partitioned.
PARTITION_KEYS: dict[str, str | None] = {
    "Apps": "creationTime",
    "Users": "creationTime",
    "Contracts": None,
    "Transactions": "transactionDate",
    "AppUsers": "creationTime",
    "Roles": None,
    "ActionExecutions": "creationTime",
    "FieldsMetadata": None,
}

# Entities whose `/{entity}/metadata` endpoint lists their predefined and custom field definitions.
# All four land in the one FieldsMetadata table, told apart by the `entity` column.
METADATA_ENTITIES = ("apps", "users", "contracts", "transactions")


@dataclass(frozen=True)
class ToriiFanoutEndpoint:
    name: str
    path: str
    page_size: int = PAGE_SIZE
    data_selector: str = ""
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


FANOUT_ENDPOINTS: dict[str, ToriiFanoutEndpoint] = {
    "Apps": ToriiFanoutEndpoint(name="Apps", path="/apps", data_selector="apps"),
    "AppUsers": ToriiFanoutEndpoint(
        name="AppUsers",
        path="/apps/{idApp}/users",
        data_selector="users",
        fanout=DependentEndpointConfig(
            parent_name="Apps",
            resolve_param="idApp",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "idApp"},
            parent_params={"fields": "id,creationTime", "sort": "creationTime:asc"},
            # An app removed between the app listing and its user fetch has no users left to sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
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
        "Roles": {
            "name": "Roles",
            "table_name": "roles",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "roles",
                "path": "/roles",
                "paginator": "single_page",
            },
        },
        # Torii returns action executions newest first and documents no sort or time filter for them.
        "ActionExecutions": {
            "name": "ActionExecutions",
            "table_name": "action_executions",
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "data_selector": "response",
                "path": "/workflows/actionExecutions",
                "params": {
                    "size": PAGE_SIZE,
                },
            },
        },
    }
    return resources[name]
