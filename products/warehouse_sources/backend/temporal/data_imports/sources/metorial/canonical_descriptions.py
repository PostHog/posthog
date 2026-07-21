"""Canonical, documentation-sourced descriptions for Metorial endpoints and columns.

Sourced from the official Metorial API reference (https://metorial.com/api). Keyed by the endpoint
names in `settings.py` `METORIAL_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Metorial table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sessions": {
        "description": "Connections to providers that let clients interact with MCP servers.",
        "docs_url": "https://metorial.com/api/sessions",
        "columns": {
            "id": "Unique session identifier (prefixed `ses_`).",
            "status": "Session status: active, archived, or deleted.",
            "name": "Human-readable name for the session.",
            "description": "Description of the session.",
            "metadata": "Arbitrary key/value metadata attached to the session.",
            "connection_state": "Current connection state of the session.",
            "connection_url": "MCP connection URL for the session.",
            "usage": "Productive client and provider message counts for the session.",
            "providers": "The providers connected to the session.",
            "has_errors": "Whether the session recorded any errors.",
            "has_warnings": "Whether the session recorded any warnings.",
            "identity_actor_id": "Identity actor associated with the session.",
            "identity_id": "Identity associated with the session.",
            "created_at": "Timestamp when the session was created.",
            "updated_at": "Timestamp when the session was last updated.",
        },
    },
    "session_messages": {
        "description": "The MCP protocol messages exchanged during a session (read-only).",
        "docs_url": "https://metorial.com/api/session-messages",
        "columns": {
            "id": "Unique session message identifier (prefixed `smg_`).",
            "type": "Message type (e.g. tool_call).",
            "status": "Message status.",
            "source": "Where the message originated (e.g. client).",
            "session_id": "Session the message belongs to.",
            "tool_call": "Tool call details when the message represents a tool invocation.",
            "created_at": "Timestamp when the message was created.",
        },
    },
    "session_errors": {
        "description": "Errors that occurred during a session (read-only).",
        "docs_url": "https://metorial.com/api/session-errors",
        "columns": {
            "id": "Unique session error identifier (prefixed `ser_`).",
            "code": "Machine-readable error code.",
            "message": "Human-readable error message.",
            "data": "Additional structured error data.",
            "status": "Processing status of the error.",
            "session_id": "Session the error belongs to.",
            "provider_run_id": "Provider run the error occurred in, if any.",
            "connection_id": "Connection the error occurred on.",
            "group_id": "Group of similar errors this error belongs to.",
            "similar_error_count": "Number of similar errors grouped with this one.",
            "created_at": "Timestamp when the error was recorded.",
        },
    },
    "provider_runs": {
        "description": "Executions of provider operations within a session (read-only).",
        "docs_url": "https://metorial.com/api/provider-runs",
        "columns": {
            "id": "Unique provider run identifier (prefixed `prn_`).",
            "status": "Run status: running or stopped.",
            "session_id": "Session the run belongs to.",
            "session_provider_id": "Session provider the run belongs to.",
            "provider_id": "Provider that was run.",
            "connection_id": "Connection the run used.",
            "completed_at": "Timestamp when the run completed (null while running).",
            "created_at": "Timestamp when the run was created.",
            "updated_at": "Timestamp when the run was last updated.",
        },
    },
    "tool_calls": {
        "description": "Individual tool invocations within a session, tracking input, output, and status.",
        "docs_url": "https://metorial.com/api/tool-calls",
        "columns": {
            "id": "Unique tool call identifier (prefixed `tcl_`).",
            "tool_key": "Key of the tool that was invoked.",
            "type": "Tool call type.",
            "status": "Tool call status: waiting_for_response, failed, or succeeded.",
            "source": "Where the tool call originated (e.g. client).",
            "session_id": "Session the tool call belongs to.",
            "message_id": "Session message that carried the tool call.",
            "provider_run_id": "Provider run the tool call belongs to.",
            "tool": "Details of the invoked tool.",
            "input": "Input arguments passed to the tool.",
            "output": "Output returned by the tool.",
            "error": "Error details if the tool call failed.",
            "created_at": "Timestamp when the tool call was created.",
        },
    },
    "provider_deployments": {
        "description": "Running provider instances pinned to a specific provider version.",
        "docs_url": "https://metorial.com/api/provider-deployments",
        "columns": {
            "id": "Unique provider deployment identifier (prefixed `pde_`).",
            "status": "Deployment status: active, archived, or deleted.",
            "name": "Human-readable name for the deployment.",
            "description": "Description of the deployment.",
            "metadata": "Arbitrary key/value metadata attached to the deployment.",
            "tool_filter": "Filter controlling which tools the deployment exposes.",
            "provider_id": "Provider this deployment runs.",
            "locked_version": "The pinned provider version the deployment runs.",
            "default_config": "Default configuration for the deployment.",
            "created_at": "Timestamp when the deployment was created.",
            "updated_at": "Timestamp when the deployment was last updated.",
        },
    },
    "providers": {
        "description": "Read-only catalog of MCP server integration templates available on Metorial.",
        "docs_url": "https://metorial.com/api/providers",
        "columns": {
            "id": "Unique provider identifier (prefixed `pro_`).",
            "access": "Provider access level (e.g. public).",
            "status": "Provider status.",
            "publisher": "Publisher of the provider.",
            "current_version": "The current published version of the provider.",
            "oauth": "OAuth configuration for the provider, if any.",
            "identifier": "Stable identifier for the provider.",
            "name": "Display name of the provider.",
            "description": "Description of the provider.",
            "slug": "URL-friendly slug for the provider.",
            "metadata": "Arbitrary key/value metadata attached to the provider.",
            "created_at": "Timestamp when the provider was created.",
            "updated_at": "Timestamp when the provider was last updated.",
        },
    },
}
