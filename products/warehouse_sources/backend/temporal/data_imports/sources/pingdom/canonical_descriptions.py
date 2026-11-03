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
    "transaction_checks": {
        "description": "A transaction check that runs a scripted or recorded user flow (TMS) against a site.",
        "docs_url": "https://docs.pingdom.com/api/#tag/TMS-Checks",
        "columns": {
            "id": "Unique identifier for the transaction check.",
            "name": "The transaction check's display name.",
            "type": "Type of transaction check: script for regular TMS checks, recording for Transaction Recorder checks.",
            "active": "Whether the transaction check is active.",
            "status": "Whether the check is currently passing or failing (successful, failing, unknown).",
            "interval": "How often the check runs, in minutes.",
            "region": "Region where the check runs (us-east, us-west, eu, au).",
            "tags": "Tags applied to the transaction check.",
            "created_at": "Time at which the check was created, as a Unix timestamp.",
            "modified_at": "Time at which the check was last modified, as a Unix timestamp.",
            "last_downtime_start": "Time the last downtime started, as a Unix timestamp.",
            "last_downtime_end": "Time the last downtime ended, as a Unix timestamp.",
        },
    },
    "results": {
        "description": "A raw test result for an uptime check, recorded by one probe at one point in time.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Results",
        "columns": {
            "checkid": "ID of the check the result belongs to.",
            "probeid": "ID of the probe that ran the test.",
            "time": "Time of the test, as a Unix timestamp.",
            "status": "Result of the test (up, down, unconfirmed, unknown).",
            "responsetime": "Response time of the test, in milliseconds.",
            "statusdesc": "Short description of the test status.",
            "statusdesclong": "Long description of the test status.",
        },
    },
    "outages": {
        "description": "A period during which an uptime check stayed in one status. Consecutive rows form the check's up/down history; the first row of each check starts at the start of the synced window.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Summary.outage",
        "columns": {
            "checkid": "ID of the check the status period belongs to.",
            "status": "Status of the check during the period (up, down, unknown).",
            "timefrom": "Start of the period, as a Unix timestamp.",
            "timeto": "End of the period, as a Unix timestamp.",
        },
    },
    "performance": {
        "description": "Hourly response-time and uptime summary for an uptime check.",
        "docs_url": "https://docs.pingdom.com/api/#tag/Summary.performance",
        "columns": {
            "checkid": "ID of the check the summary belongs to.",
            "starttime": "Start of the hour, as a Unix timestamp.",
            "avgresponse": "Average response time during the hour, in milliseconds.",
            "uptime": "Total uptime during the hour, in seconds.",
            "downtime": "Total downtime during the hour, in seconds.",
            "unmonitored": "Total unmonitored time during the hour, in seconds.",
        },
    },
}
