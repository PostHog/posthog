"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="external_data_source",
        name="External data source",
        plural="external data sources",
        description="Data warehouse sources, their synced tables and sync settings, and the destinations they write to.",
        group="Data warehouse & pipelines",
        docs_url="https://posthog.com/docs/data-pipelines/sources",
    ),
)
