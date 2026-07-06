from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PingdomEndpointConfig:
    name: str
    path: str
    # Dotted path to the list of rows in the response body (e.g. "actions.alerts"
    # for the nested {"actions": {"alerts": [...]}} wrapper).
    data_key: str
    # Alerts have no unique id, so the primary key can be composite.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    # Max page size the endpoint accepts (checks allow 25000, actions 1000).
    page_size: int = 1000
    # Composite keys on alerts may still collide (same check/user/second/channel).
    has_duplicate_primary_keys: bool = False


# Pingdom API 3.1 timestamps are UNIX epoch seconds. Only /actions exposes a
# server-side `from`/`to` time filter among the endpoints we sync; /checks,
# /probes and /maintenance are small full-refresh dimension tables.
PINGDOM_ENDPOINTS: dict[str, PingdomEndpointConfig] = {
    "checks": PingdomEndpointConfig(
        name="checks",
        path="/checks",
        data_key="checks",
        page_size=25000,
    ),
    "probes": PingdomEndpointConfig(
        name="probes",
        path="/probes",
        data_key="probes",
    ),
    "maintenance": PingdomEndpointConfig(
        name="maintenance",
        path="/maintenance",
        data_key="maintenance",
    ),
    "alerts": PingdomEndpointConfig(
        name="alerts",
        path="/actions",
        data_key="actions.alerts",
        # Alert rows carry no id; (checkid, time, userid, via) is the closest
        # natural key and can still collide, so flag duplicates for the pipeline.
        primary_keys=["checkid", "time", "userid", "via"],
        partition_key="time",
        page_size=1000,
        has_duplicate_primary_keys=True,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(PINGDOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PINGDOM_ENDPOINTS.items() if config.incremental_fields
}
