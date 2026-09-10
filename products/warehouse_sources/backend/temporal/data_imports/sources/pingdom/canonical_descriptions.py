"""Canonical, documentation-sourced descriptions for Pingdom endpoints and columns.

Sourced from the official Pingdom API 3.1 reference (https://docs.pingdom.com/api/). Keyed by the
endpoint names in `settings.py` `PINGDOM_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Pingdom table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "checks": {
        "description": "An uptime check that monitors the availability of a host or service from Pingdom.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Checks",
        "columns": {
            "id": "Unique identifier for the check.",
            "name": "The check's display name.",
            "hostname": "Target host or URL being monitored.",
            "type": "Type of check (e.g. http, tcp, ping, dns).",
            "status": "Current status of the check (e.g. up, down, paused, unknown).",
            "resolution": "How often the check runs, in minutes.",
            "lasttesttime": "Time the check was last tested, as a Unix timestamp.",
            "lastresponsetime": "Response time of the last test, in milliseconds.",
            "lasterrortime": "Time of the last error, as a Unix timestamp.",
            "created": "Time at which the check was created, as a Unix timestamp.",
            "paused": "Whether the check is currently paused.",
            "tags": "Tags applied to the check for grouping and filtering.",
        },
    },
    "probes": {
        "description": "A Pingdom probe server that runs checks from a specific geographic location.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Probes",
        "columns": {
            "id": "Unique identifier for the probe.",
            "name": "Human-readable name of the probe location.",
            "country": "Country where the probe is located.",
            "city": "City where the probe is located.",
            "region": "Geographic region the probe belongs to.",
            "active": "Whether the probe is currently active.",
            "hostname": "Hostname of the probe server.",
            "ip": "IPv4 address of the probe.",
            "ipv6": "IPv6 address of the probe.",
            "countryiso": "ISO country code of the probe's location.",
        },
    },
    "maintenance": {
        "description": "A scheduled maintenance window during which checks are paused.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Maintenance",
        "columns": {
            "id": "Unique identifier for the maintenance window.",
            "description": "Description of the maintenance window.",
            "from": "Start time of the maintenance window, as a Unix timestamp.",
            "to": "End time of the maintenance window, as a Unix timestamp.",
            "recurrencetype": "How the maintenance window recurs (e.g. none, day, week, month).",
            "repeatevery": "Interval between recurrences, in units of recurrencetype.",
            "effectiveto": "Time after which the recurring maintenance no longer applies, as a Unix timestamp.",
            "checks": "The checks and uptime checks covered by this maintenance window.",
        },
    },
    "alerts": {
        "description": "An alert action triggered by a check state change, such as a notification sent to a user.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Actions",
        "columns": {
            "checkid": "ID of the check that triggered the alert.",
            "checkname": "Name of the check that triggered the alert.",
            "time": "Time the alert was triggered, as a Unix timestamp.",
            "userid": "ID of the user the alert was sent to.",
            "username": "Name of the user the alert was sent to.",
            "via": "Channel the alert was sent through (e.g. email, sms, webhook).",
            "status": "Status reported by the alert (e.g. up, down, sent, delivered).",
            "messageshort": "Short description of the alert message.",
            "messagefull": "Full text of the alert message.",
        },
    },
}
