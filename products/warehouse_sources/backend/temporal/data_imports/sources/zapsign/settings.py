from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ZAPSIGN_BASE_URL = "https://api.zapsign.com.br"
ZAPSIGN_SANDBOX_BASE_URL = "https://sandbox.api.zapsign.com.br"

DOCUMENTS_RESOURCE = "documents"
TEMPLATES_RESOURCE = "templates"
SIGNERS_RESOURCE = "signers"

ENDPOINTS = (
    DOCUMENTS_RESOURCE,
    TEMPLATES_RESOURCE,
    SIGNERS_RESOURCE,
)

# Only the documents list exposes a server-side time filter (`created_from`/`created_to`, on the
# creation date). ZapSign has no `updated_at` filter anywhere, so `created_at` is the sole
# incremental cursor; templates and signers are full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    DOCUMENTS_RESOURCE: [incremental_field("created_at", IncrementalFieldType.DateTime)],
    TEMPLATES_RESOURCE: [],
    SIGNERS_RESOURCE: [],
}

ENDPOINT_PATHS: dict[str, str] = {
    DOCUMENTS_RESOURCE: "/api/v1/docs/",
    TEMPLATES_RESOURCE: "/api/v1/templates/",
}

# Signers have no list endpoint of their own — they're read from each document's detail response.
DOCUMENT_DETAIL_PATH = "/api/v1/docs/{token}/"

PRIMARY_KEYS: dict[str, list[str]] = {
    DOCUMENTS_RESOURCE: ["token"],
    TEMPLATES_RESOURCE: ["token"],
    # Signer tokens look globally unique, but ZapSign doesn't document that guarantee, so the
    # parent document token stays in the key (`_documents_token` is injected by the fan-out).
    SIGNERS_RESOURCE: ["_documents_token", "token"],
}

# `created_at` never changes after creation, unlike `last_update_at`, so partitions stay stable.
PARTITION_KEYS: dict[str, list[str]] = {
    DOCUMENTS_RESOURCE: ["created_at"],
    TEMPLATES_RESOURCE: ["created_at"],
}

# String timestamp columns coerced to datetimes by the framework's `convert_types`.
TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    DOCUMENTS_RESOURCE: ("created_at", "last_update_at"),
    TEMPLATES_RESOURCE: ("created_at", "last_update_at"),
    SIGNERS_RESOURCE: ("last_view_at", "signed_at"),
}
