from __future__ import annotations

import re

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")
_DUCKGRES_IDENTIFIER_MAX_LENGTH = 63


def duckgres_data_imports_table_name_for_version(
    source_type: str,
    prefix: str | None,
    normalized_name: str,
    naming_version: str,
) -> str:
    raw_name = f"{source_type}_{prefix}_{normalized_name}" if prefix else f"{source_type}_{normalized_name}"
    if naming_version == "copy_v1":
        return _sanitize_identifier(raw_name, default_prefix="data_import")
    if naming_version == "legacy_batch_v1":
        return NamingConvention.normalize_identifier(raw_name, max_length=_DUCKGRES_IDENTIFIER_MAX_LENGTH)
    raise ValueError(f"Unsupported Duckgres data imports table naming version: {naming_version!r}")


def _sanitize_identifier(raw: str, *, default_prefix: str) -> str:
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:_DUCKGRES_IDENTIFIER_MAX_LENGTH]
