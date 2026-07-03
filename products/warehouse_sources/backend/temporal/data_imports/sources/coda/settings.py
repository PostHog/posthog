from dataclasses import dataclass, field


@dataclass
class CodaEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Coda's list endpoints have no updated-since filters (rows only sort), so
# every stream is a full refresh. Rows fan out docs → tables → rows; ids are
# only unique within their parent, hence the composite keys.
CODA_ENDPOINTS: dict[str, CodaEndpointConfig] = {
    "docs": CodaEndpointConfig(
        name="docs",
    ),
    "tables": CodaEndpointConfig(
        name="tables",
        primary_keys=["_doc_id", "id"],
    ),
    "rows": CodaEndpointConfig(
        name="rows",
        primary_keys=["_doc_id", "_table_id", "id"],
    ),
}

ENDPOINTS = tuple(CODA_ENDPOINTS.keys())
