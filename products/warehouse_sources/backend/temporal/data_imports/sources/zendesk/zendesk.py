import re
import base64
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from requests import Request, Response

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONLinkPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    ParentRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    parent_snapshot_covers_through,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.settings import (
    FANOUT_PARENTS,
    TICKET_COMMENTS_PARENT_FILTER_FIELD,
    TICKET_COMMENTS_PARENT_LOOKBACK,
    TICKET_COMMENTS_PARENT_MAX_CATCHUP,
    ZENDESK_ENDPOINTS,
    ZendeskEndpointConfig,
)

# Lower bound for the ISO 8601 time filters on the first run / full refresh, mirroring the `0`
# epoch seed the incremental exports use.
ZENDESK_EPOCH_START = "1970-01-01T00:00:00Z"


def to_zendesk_start_time(value: Any) -> int:
    """Convert an incremental cursor value to the Unix epoch seconds Zendesk's incremental
    export `start_time` expects. Applied to both the persisted last value (a `datetime` for
    DateTime incremental fields) and the `initial_value` (0) on the first run / full refresh."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    return int(value)


def to_zendesk_iso8601(value: Any) -> str:
    """Format an incremental cursor value for the ISO 8601 UTC filters (`since`) on the plain
    Support list endpoints, which — unlike the incremental exports — don't take Unix epochs."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def zendesk_incremental_window(start_param: str, cursor_path: str) -> IncrementalConfig:
    return {
        "start_param": start_param,
        "cursor_path": cursor_path,
        "initial_value": ZENDESK_EPOCH_START,
        "convert": to_zendesk_iso8601,
    }


def _bounded_fanout(fanout: DependentEndpointConfig, db_incremental_field_last_value: Any) -> DependentEndpointConfig:
    """Bound a warehouse parent scan to the tickets whose comments may have changed.

    The floor is the child's own watermark, so the scan covers exactly what the previous run did
    not: a comment added, redacted, or made private since then moved its ticket's `updated_at`.

    Two cases have no floor that is both safe and complete, and both take the parent-API path the
    feature already falls back to. Without a watermark there is nothing to scan from. With a
    watermark older than Zendesk's archive delay, a scan wide enough to cover the gap reaches
    tickets `/api/v2/tickets` no longer lists, so it would fan out wider than the API path rather
    than narrower.
    """
    if fanout.parent_source != "warehouse":
        return fanout

    now = datetime.now(UTC)
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None or watermark < now - TICKET_COMMENTS_PARENT_MAX_CATCHUP:
        return dataclasses.replace(fanout, parent_source="api")

    return dataclasses.replace(
        fanout,
        parent_row_filter=ParentRowFilter(
            field=TICKET_COMMENTS_PARENT_FILTER_FIELD,
            # A watermark ahead of now would floor the scan in the future and read nothing.
            not_before=min(watermark, now) - TICKET_COMMENTS_PARENT_LOOKBACK,
        ),
    )


def _fanout_incremental_config(config: ZendeskEndpointConfig) -> Callable[[str], IncrementalConfig | None]:
    """Build the child's request window, or report that the endpoint has none.

    A plain list endpoint without a start param is a config error (`get_declarative_resource`
    raises). A fan-out child is different: the parent bounds which rows it requests, so a child
    endpoint that takes no time filter still merges rather than replaces.
    """

    def _factory(cursor_path: str) -> IncrementalConfig | None:
        if config.incremental_start_param is None:
            return None
        return zendesk_incremental_window(config.incremental_start_param, cursor_path)

    return _factory


def paginator_for(config: ZendeskEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    if config.next_url_path == "after_url":
        return ZendeskAfterUrlPaginator()
    return JSONLinkPaginator(next_url_path=config.next_url_path)


def get_declarative_resource(
    config: ZendeskEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    """Build a resource for one of the plain Support API list endpoints in `ZENDESK_ENDPOINTS`."""
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{config.name}' must be built through the fan-out path")

    params: dict[str, Any] = dict(config.params)
    if config.paginated:
        params["page[size]"] = config.page_size

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
        # Every one of these responses wraps its rows in a documented key, so a response without
        # it means the API shape changed — fail loud rather than silently syncing 0 rows.
        "data_selector_required": True,
        "paginator": paginator_for(config),
    }

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    if use_incremental:
        if config.incremental_start_param is None:
            raise ValueError(f"Endpoint '{config.name}' advertises incremental fields but has no start param")
        endpoint_config["incremental"] = zendesk_incremental_window(
            config.incremental_start_param,
            incremental_field_name or config.default_incremental_field or "created_at",
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "brands": {
            "name": "brands",
            "table_name": "brands",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_brands"),
            "endpoint": {
                "data_selector": "brands",
                "path": "/api/v2/brands",
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "organizations": {
            "name": "organizations",
            "table_name": "organizations",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_organizations"),
            "endpoint": {
                "data_selector": "organizations",
                # Time-based incremental export (no cursor variant exists for organizations).
                "path": "/api/v2/incremental/organizations",
                "paginator": ZendeskIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "updated_at",
                        "initial_value": 0,
                        "convert": to_zendesk_start_time,
                    },
                },
            },
            "table_format": "delta",
        },
        "groups": {
            "name": "groups",
            "table_name": "groups",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_groups"),
            "endpoint": {
                "data_selector": "groups",
                "path": "/api/v2/groups",
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    # the parameters below can optionally be configured
                    # "exclude_deleted": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "sla_policies": {
            "name": "sla_policies",
            "table_name": "sla_policies",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_sla_policies"),
            "endpoint": {
                "data_selector": "sla_policies",
                "path": "/api/v2/slas/policies",
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
            },
            "table_format": "delta",
        },
        "users": {
            "name": "users",
            "table_name": "users",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_users"),
            "endpoint": {
                "data_selector": "users",
                # Cursor-based incremental export (recommended over the time-based variant).
                "path": "/api/v2/incremental/users/cursor",
                "paginator": ZendeskCursorIncrementalPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "updated_at",
                        "initial_value": 0,
                        "convert": to_zendesk_start_time,
                    },
                },
            },
            "table_format": "delta",
        },
        "ticket_fields": {
            "name": "ticket_fields",
            "table_name": "ticket_fields",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_fields"),
            "endpoint": {
                "data_selector": "ticket_fields",
                "path": "/api/v2/ticket_fields",
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    # the parameters below can optionally be configured
                    # "locale": "OPTIONAL_CONFIG",
                    # "creator": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "ticket_events": {
            "name": "ticket_events",
            "table_name": "ticket_events",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_events"),
            "endpoint": {
                "data_selector": "ticket_events",
                "path": "/api/v2/incremental/ticket_events",
                "paginator": ZendeskIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    # Enrich each event's `child_events` with the full comment body
                    # (public replies and internal notes); without it bodies are stripped.
                    "include": "comment_events",
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created_at",
                        "initial_value": 0,
                        "convert": to_zendesk_start_time,
                    },
                },
            },
            "table_format": "delta",
        },
        "tickets": {
            "name": "tickets",
            "table_name": "tickets",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_tickets"),
            "endpoint": {
                "data_selector": "tickets",
                # Cursor-based incremental export. The time-based export
                # (`/api/v2/incremental/tickets`) deadlocks when >1000 tickets
                # share a `generated_timestamp`: the page never advances past
                # that timestamp, so pagination loops forever re-fetching the
                # same boundary page. Cursor pagination is immune to this.
                "path": "/api/v2/incremental/tickets/cursor",
                "paginator": ZendeskCursorIncrementalPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "generated_timestamp",
                        "initial_value": 0,
                    },
                },
            },
            "table_format": "delta",
        },
        "ticket_metric_events": {
            "name": "ticket_metric_events",
            "table_name": "ticket_metric_events",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_metric_events"),
            "endpoint": {
                "data_selector": "ticket_metric_events",
                "path": "/api/v2/incremental/ticket_metric_events",
                "paginator": ZendeskIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "time",
                        "initial_value": 0,
                        "convert": to_zendesk_start_time,
                    },
                },
            },
            "table_format": "delta",
        },
    }

    if name in resources:
        return resources[name]

    return get_declarative_resource(ZENDESK_ENDPOINTS[name], should_use_incremental_field, incremental_field_name)


class ZendeskCursorIncrementalPaginator(BasePaginator):
    """Cursor-based pagination for Zendesk's cursor incremental exports (tickets, users).

    The first request is seeded with `start_time` (resolved from the incremental
    cursor); every subsequent request follows the opaque `after_cursor` token.
    Unlike the time-based export, the cursor encodes the stream position rather
    than a timestamp, so it can't get pinned when many records share a timestamp.
    Only the top-level `after_cursor`/`end_of_stream` fields are read, so this works
    for any cursor incremental export regardless of the resource's data key.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after_cursor: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        if "end_of_stream" not in res:
            raise ValueError("Zendesk cursor export response is missing 'end_of_stream'")

        if res["end_of_stream"]:
            self._has_next_page = False
            return

        # `end_of_stream` is False, so the stream continues and a valid, advancing
        # `after_cursor` must be present. A missing or non-advancing cursor is an
        # invalid/partial response — raise so the activity retries instead of
        # committing truncated data as a successful sync.
        after_cursor = res.get("after_cursor")
        if not after_cursor or after_cursor == self._after_cursor:
            raise ValueError("Zendesk cursor export returned end_of_stream=False without an advancing after_cursor")

        self._after_cursor = after_cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        # After the first page we paginate purely by cursor; drop the seed
        # `start_time` so it doesn't conflict with the `cursor` param.
        request.params.pop("start_time", None)
        request.params["cursor"] = self._after_cursor


class ZendeskIncrementalEndpointPaginator(BasePaginator):
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._next_page = None

        if not res:
            self._has_next_page = False
            return

        if "end_of_stream" not in res:
            raise ValueError("Zendesk incremental export response is missing 'end_of_stream'")

        if res["end_of_stream"]:
            self._has_next_page = False
            return

        # `end_of_stream` is False, so the stream continues and `next_page` must be
        # present. A missing `next_page` is an invalid/partial response — raise so the
        # activity retries instead of committing truncated data as a successful sync.
        next_page = res.get("next_page")
        if not next_page:
            raise ValueError("Zendesk incremental export returned end_of_stream=False without a next_page")

        self._next_page = next_page
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        request.url = self._next_page
        # next_page is a full URL that already contains all query params —
        # clear params to avoid duplicates when prepare_request merges them.
        request.params = {}


class ZendeskAfterUrlPaginator(JSONLinkPaginator):
    """Cursor pagination for `/api/v2/ticket_audits`, which returns its next-page link as
    `after_url` rather than the `links.next` the newer list endpoints use.

    An empty page also terminates: the endpoint keeps handing back a cursor URL once the stream
    is exhausted, so the link on its own isn't a reliable stop condition.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="after_url")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is not None and len(data) == 0:
            self._has_next_page = False
            return
        super().update_state(response, data)


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Zendesk subdomain label.

    Users frequently paste the full host ("nibbles.zendesk.com") or a URL
    ("https://nibbles.zendesk.com/") into the subdomain field. Without normalizing,
    the base URL becomes "https://nibbles.zendesk.com.zendesk.com/", whose doubled
    host the TLS handshake rejects (SSLV3_ALERT_HANDSHAKE_FAILURE) and never recovers.
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    # Drop any path/query left over from a pasted URL.
    subdomain = subdomain.split("/", 1)[0]
    # Strip a trailing ".zendesk.com" so a full host collapses to the subdomain label.
    return re.sub(r"\.zendesk\.com$", "", subdomain, flags=re.IGNORECASE)


def zendesk_client_config(subdomain: str, api_key: str, email_address: str) -> ClientConfig:
    return {
        "base_url": f"https://{normalize_subdomain(subdomain)}.zendesk.com/",
        "auth": {
            "type": "http_basic",
            "username": f"{email_address}/token",
            "password": api_key,
        },
    }


def zendesk_fanout_source(
    client_config: ClientConfig,
    config: ZendeskEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field_name: str | None = None,
    source_id: str | None = None,
    use_warehouse_parent: bool = False,
) -> Resource:
    """Fan out over a parent list endpoint, then page the child endpoint per parent row."""
    assert config.fanout is not None
    fanout = _bounded_fanout(config.fanout, db_incremental_field_last_value)

    # How far the tickets snapshot is guaranteed complete. The comments fanned out below are
    # fetched live, so emitting one past this point would carry this schema's watermark over
    # ticket changes the snapshot could not show it, and the next run's floor would skip them for
    # good. Capping defers those comments by one run instead, so nothing is lost. Read before
    # `build_dependent_resource` pins the table, never after — see the helper's docstring. Without
    # a completed parent sync there is no cap, so the run takes the API path, whose listing is
    # live and needs none.
    snapshot_at: datetime | None = None
    if fanout.parent_source == "warehouse" and use_warehouse_parent:
        snapshot_at = parent_snapshot_covers_through(team_id, source_id or "", fanout.parent_name)
        if snapshot_at is None:
            fanout = dataclasses.replace(fanout, parent_source="api")

    parent = FANOUT_PARENTS[fanout.parent_name]
    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs={config.name: config, parent.name: parent},
            child_endpoint=config.name,
            fanout=fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field_name,
            incremental_config_factory=_fanout_incremental_config(config),
            page_size_param="page[size]",
            parent_endpoint_extra={
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
                "data_selector": parent.data_selector,
            },
            child_endpoint_extra={
                "paginator": paginator_for(config),
                "data_selector": config.data_selector,
            },
            source_id=source_id,
            use_warehouse_parent=use_warehouse_parent,
            parent_snapshot_at=snapshot_at,
        ),
    )


def zendesk_source(
    subdomain: str,
    api_key: str,
    email_address: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field_name: str | None = None,
    source_id: str | None = None,
    use_warehouse_parent: bool = False,
):
    client_config = zendesk_client_config(subdomain, api_key, email_address)

    endpoint_config = ZENDESK_ENDPOINTS.get(endpoint)
    if endpoint_config is not None and endpoint_config.fanout is not None:
        return zendesk_fanout_source(
            client_config,
            endpoint_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            should_use_incremental_field,
            incremental_field_name,
            source_id=source_id,
            use_warehouse_parent=use_warehouse_parent,
        )

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field_name)],
    }

    return rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(subdomain: str, api_key: str, email_address: str) -> bool:
    basic_token = base64.b64encode(f"{email_address}/token:{api_key}".encode("ascii")).decode("ascii")
    res = make_tracked_session().get(
        f"https://{normalize_subdomain(subdomain)}.zendesk.com/api/v2/tickets/count",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
