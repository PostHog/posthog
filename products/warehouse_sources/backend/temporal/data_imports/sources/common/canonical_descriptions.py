"""Curated, documentation-sourced descriptions for well-known source tables/endpoints.

Fixed-schema sources (SaaS APIs like Stripe or Hubspot) expose the same tables and columns for
everyone, so their semantics are known up front from the official API docs. Capturing those once —
keyed by schema/endpoint name — lets the data warehouse describe them deterministically and
consistently across every team, instead of asking an LLM to re-derive them per team.

Each source ships its own `canonical_descriptions.py` and exposes it via
``Source.get_canonical_descriptions()``. A missing source file, endpoint, or column simply falls
back to the LLM enrichment pass. SQL sources (arbitrary user schemas) ship nothing here.
"""

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from products.warehouse_sources.backend.types import ExternalDataSourceType


class CanonicalEndpoint(TypedDict, total=False):
    """Doc-sourced description of one endpoint/table. All fields optional."""

    description: str  # one-line table/endpoint description
    docs_url: str  # link to the source's API docs for this endpoint
    columns: dict[str, str]  # column name -> one-line description


# Keyed by schema/endpoint name (matching the names a source's `get_schemas` returns).
CanonicalDescriptions = dict[str, CanonicalEndpoint]


def get_canonical_descriptions_for_source(source_type: "ExternalDataSourceType | str") -> CanonicalDescriptions:
    """Resolve a source's curated descriptions via the registry. ``{}`` when the source ships none.

    Accepts the raw `ExternalDataSource.source_type` string (or the enum) and normalizes it; an
    unknown value resolves to ``{}``.
    """
    # Imported lazily: the registry pulls in every source's (often heavy) dependencies on first use.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (
        SourceRegistry,  # noqa: PLC0415
    )
    from products.warehouse_sources.backend.types import ExternalDataSourceType  # noqa: PLC0415

    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    except Exception:
        return {}
    try:
        return source.get_canonical_descriptions()
    except Exception:
        return {}
