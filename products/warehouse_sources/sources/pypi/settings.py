from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# A file's upload time never changes once published, so it's a stable partition key for the
# releases stream. We expose the raw ISO 8601 string PyPI already returns (`upload_time_iso_8601`).
_UPLOAD_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "upload_time_iso_8601",
        "type": IncrementalFieldType.DateTime,
        "field": "upload_time_iso_8601",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class PyPIEndpointConfig:
    name: str
    # Where the rows for this stream live inside the JSON project document
    # (GET /pypi/<project>/json). Handled explicitly per stream in `pypi.py`.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column used for partitioning, or `None` for streams without one.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    description: Optional[str] = None


PYPI_ENDPOINTS: dict[str, PyPIEndpointConfig] = {
    "projects": PyPIEndpointConfig(
        name="projects",
        # PyPI project names are globally unique (normalized per PEP 503).
        primary_keys=["name"],
        description="Project (package) metadata: one row per configured package, from the `info` "
        "block of the JSON API.",
    ),
    "releases": PyPIEndpointConfig(
        name="releases",
        # A distribution filename is unique within a version, but versions and packages aggregate
        # into one table, so the package + version + filename together form the key.
        primary_keys=["package", "version", "filename"],
        incremental_fields=list(_UPLOAD_TIME_INCREMENTAL_FIELDS),
        partition_key="upload_time_iso_8601",
        description="Release files: one row per uploaded distribution file across every version of "
        "each configured package.",
    ),
    "vulnerabilities": PyPIEndpointConfig(
        name="vulnerabilities",
        # Vulnerability ids are unique per advisory source but rows aggregate across packages.
        primary_keys=["package", "id"],
        description="Known vulnerabilities affecting the latest version of each configured package, "
        "as reported by the PyPI JSON API.",
    ),
}

ENDPOINTS = tuple(PYPI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PYPI_ENDPOINTS.items()
}
