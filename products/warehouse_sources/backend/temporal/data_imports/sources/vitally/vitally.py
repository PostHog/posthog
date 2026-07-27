import base64
from datetime import datetime
from typing import Any, Optional

from dateutil import parser
from requests import HTTPError, JSONDecodeError, Request, Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.settings import (
    CUSTOM_OBJECT_SCHEMA_PREFIX,
)


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Organizations": {
            "name": "Organizations",
            "table_name": "organizations",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/organizations",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Accounts": {
            "name": "Accounts",
            "table_name": "accounts",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/accounts",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "status": "activeOrChurned",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Users": {
            "name": "Users",
            "table_name": "users",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/users",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Conversations": {
            "name": "Conversations",
            "table_name": "conversations",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/conversations",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Notes": {
            "name": "Notes",
            "table_name": "notes",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/notes",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Projects": {
            "name": "Projects",
            "table_name": "projects",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/projects",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Tasks": {
            "name": "Tasks",
            "table_name": "tasks",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/tasks",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "NPS_Responses": {
            "name": "NPS_Responses",
            "table_name": "nps_responses",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/npsResponses",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Custom_Objects": {
            "name": "Custom_Objects",
            "table_name": "custom_objects",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/customObjects",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


def get_custom_object_records_resource(
    custom_object_machine_name: str, custom_object_id: str, should_use_incremental_field: bool
) -> EndpointResource:
    """Build an EndpointResource that pulls records (instances) for a single Vitally custom object.

    See https://docs.vitally.io/pushing-data-to-vitally/rest-api/custom-objects — list endpoint is
    `/resources/customObjects/:customObjectId/instances`.
    """
    return {
        "name": f"{CUSTOM_OBJECT_SCHEMA_PREFIX}{custom_object_machine_name}",
        "table_name": f"custom_object_{custom_object_machine_name.lower()}",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "results",
            "path": f"/resources/customObjects/{custom_object_id}/instances",
            "params": {
                "limit": 100,
                "sortBy": "updatedAt",
                "updatedAt": {
                    "type": "incremental",
                    "cursor_path": "updatedAt",
                    "initial_value": "1970-01-01",
                    "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                }
                if should_use_incremental_field
                else None,
            },
        },
        "table_format": "delta",
    }


def list_custom_object_definitions(secret_token: str, region: str, subdomain: Optional[str]) -> list[dict[str, Any]]:
    """Page through the Vitally custom object *definitions* endpoint.

    Used at schema discovery time to enumerate every custom object the workspace has,
    and at sync time to resolve a `Custom_Object_<machineName>` schema back to its UUID
    (Vitally instance endpoints require the id, not the name)."""
    paginator = VitallyPaginator(incremental_start_value=None, should_use_incremental_field=False)
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")

    request = Request(
        "get",
        url=f"{get_base_url(region, subdomain)}resources/customObjects",
        params={"limit": 100},
        headers={"Authorization": f"Basic {basic_token}"},
    )

    results: list[dict[str, Any]] = []
    with make_tracked_session() as session:
        while paginator.has_next_page:
            paginator.update_request(request)
            prepared = session.prepare_request(request)
            response = session.send(prepared)
            response.raise_for_status()
            data = response.json()
            results.extend(data.get("results") or [])
            paginator.update_state(response)

    return results


class VitallyPaginator(BasePaginator):
    _incremental_start_value: Any
    _should_use_incremental_field: bool = False
    _cursor: str | None = None

    def __init__(self, incremental_start_value: Any, should_use_incremental_field: bool) -> None:
        self._incremental_start_value = incremental_start_value
        self._should_use_incremental_field = should_use_incremental_field

        super().__init__()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._cursor = None

        if not res:
            self._has_next_page = False
            return

        if self._should_use_incremental_field and self._incremental_start_value is not None:
            results = res.get("results")
            if not results:
                self._has_next_page = False
                return

            updated_at_str = results[0]["updatedAt"]
            updated_at = parser.parse(updated_at_str).timestamp()
            if isinstance(self._incremental_start_value, str):
                start_value = parser.parse(self._incremental_start_value).timestamp()
            elif isinstance(self._incremental_start_value, datetime):
                start_value = self._incremental_start_value.timestamp()
            else:
                raise TypeError("_incremental_start_value type is not supported for Vitally paginator")

            if start_value >= updated_at:
                self._has_next_page = False
                return

        if res["next"]:
            self._has_next_page = True
            self._cursor = res["next"]
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["from"] = self._cursor


def get_messages(
    secret_token: str,
    region: str,
    subdomain: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
):
    """Messages are a field on conversations which only get returned
    when you request each conversation individually. This queries
    for conversations and then gets and yields the messages for each
    conversation."""

    paginator = VitallyPaginator(
        incremental_start_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
    )
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")

    params: dict[str, Any] = {
        "limit": 100,
        "sortBy": "updatedAt",
    }

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            params["updatedAt"] = (
                parser.parse(db_incremental_field_last_value).timestamp()
                if not isinstance(db_incremental_field_last_value, datetime)
                else db_incremental_field_last_value
            )
        else:
            params["updatedAt"] = "1970-01-01"

    request = Request(
        "get",
        url=f"{get_base_url(region, subdomain)}resources/conversations",
        params=params,
        headers={"Authorization": f"Basic {basic_token}:"},
    )

    logger.debug("Requesting first page")

    with make_tracked_session() as session:
        while paginator.has_next_page:
            paginator.update_request(request)
            prepared_request = session.prepare_request(request)
            response = session.send(prepared_request)
            logger.debug(f"Requesting {prepared_request.url}")

            response.raise_for_status()
            results = response.json().get("results") or []

            for conversation in results:
                id = conversation.get("id")
                conversation_updated_at = conversation.get("updatedAt")
                logger.debug(f"Requesting messages for conversation {id}")

                conversation_response = session.get(
                    f"{get_base_url(region, subdomain)}resources/conversations/{id}",
                    headers={"Authorization": f"Basic {basic_token}:"},
                )

                try:
                    conversation_response.raise_for_status()

                    messages = conversation_response.json().get("messages") or []
                    logger.debug(f"Yielding {len(messages)} messages")
                    for message in messages:
                        message["conversation_updated_at"] = conversation_updated_at
                        yield message
                except HTTPError as e:
                    logger.debug(
                        f"Failed to fetch messages for conversation {id}: {conversation_response.status_code} {e}. Body: {conversation_response.text}"
                    )
                except JSONDecodeError as e:
                    logger.debug(
                        f"Failed to decode JSON response for conversation {id}: {conversation_response.status_code} {e}. Body: {conversation_response.text}"
                    )

            paginator.update_state(response)


def get_base_url(region: str, subdomain: Optional[str]) -> str:
    if region == "US" and subdomain:
        return f"https://{subdomain}.rest.vitally.io/"

    return "https://rest.vitally-eu.io/"


def vitally_source(
    secret_token: str,
    region: str,
    subdomain: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    if endpoint == "Messages":
        yield from get_messages(
            secret_token, region, subdomain, db_incremental_field_last_value, should_use_incremental_field, logger
        )
        return

    if endpoint.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX):
        machine_name = endpoint[len(CUSTOM_OBJECT_SCHEMA_PREFIX) :]
        definitions = list_custom_object_definitions(secret_token, region, subdomain)
        match = next((d for d in definitions if d.get("name") == machine_name), None)
        if match is None or not match.get("id"):
            raise ValueError(
                f"Vitally custom object '{machine_name}' could not be resolved. "
                "It may have been deleted or renamed in Vitally; refresh source schemas to pick up the new name."
            )
        endpoint_resource = get_custom_object_records_resource(machine_name, match["id"], should_use_incremental_field)
    else:
        endpoint_resource = get_resource(endpoint, should_use_incremental_field)

    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(region, subdomain),
            "auth": {
                "type": "http_basic",
                "username": secret_token,
                "password": "",
            },
            "paginator": VitallyPaginator(
                incremental_start_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            ),
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [endpoint_resource],
    }

    yield from rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(secret_token: str, region: str, subdomain: Optional[str]) -> bool:
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")
    res = make_tracked_session().get(
        f"{get_base_url(region, subdomain)}resources/users?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
