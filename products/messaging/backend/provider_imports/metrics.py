"""Prometheus metrics for provider imports. Labels stay to the provider and step, never a team or contact."""

from prometheus_client import Counter, Histogram

IMPORT_CONTACTS = Counter(
    "messaging_provider_import_contacts_total",
    "Contacts an import's contacts step handled, by outcome: imported (PostHog accepted it), skipped (left out before "
    "sending, such as an invalid address or no matching person) or failed (never reached PostHog).",
    labelnames=["provider", "step", "outcome"],
)
IMPORT_CHUNK_DURATION = Histogram(
    "messaging_provider_import_chunk_duration_seconds",
    "Time one part of a contact list took to send and wait for its people, per attempt.",
    labelnames=["provider", "step"],
    buckets=(1, 2.5, 5, 10, 30, 60, 120, 300, 600, 900),
)
IMPORT_CHUNK_RETRIES = Counter(
    "messaging_provider_import_chunk_retries_total",
    "Attempts after the first at sending one part of a contact list.",
    labelnames=["provider", "step"],
)
IMPORT_RUNS = Counter(
    "messaging_provider_import_runs_total",
    "Import runs that ended, by final status.",
    labelnames=["provider", "status"],
)
