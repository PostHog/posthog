from __future__ import annotations

import enum
import functools
import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml


class DuckLakeCopyVerificationParameter(enum.StrEnum):
    """Allowed dynamic parameters that verification queries can bind."""

    TEAM_ID = "team_id"
    JOB_ID = "job_id"
    MODEL_LABEL = "model_label"
    SAVED_QUERY_ID = "saved_query_id"
    SAVED_QUERY_NAME = "saved_query_name"
    NORMALIZED_NAME = "normalized_name"
    SOURCE_TABLE_URI = "source_table_uri"
    SCHEMA_NAME = "schema_name"
    TABLE_NAME = "table_name"


@dataclasses.dataclass(frozen=True)
class DuckLakeCopyVerificationQuery:
    """Representation of a verification query defined in YAML."""

    name: str
    sql: str
    description: str | None = None
    parameters: tuple[DuckLakeCopyVerificationParameter, ...] = ()
    expected_value: float = 0.0
    tolerance: float = 0.0


@dataclasses.dataclass(frozen=True)
class _ModelVerificationConfig:
    queries: tuple[DuckLakeCopyVerificationQuery, ...] = ()
    inherit_defaults: bool = True


@dataclasses.dataclass(frozen=True)
class DuckLakeVerificationConfig:
    default_queries: tuple[DuckLakeCopyVerificationQuery, ...]
    model_overrides: dict[str, _ModelVerificationConfig]

    def queries_for_model(self, model_label: str) -> list[DuckLakeCopyVerificationQuery]:
        override = self.model_overrides.get(model_label)
        queries: list[DuckLakeCopyVerificationQuery] = []
        if override is None or override.inherit_defaults:
            queries.extend(self.default_queries)
        if override:
            queries.extend(override.queries)
        return list(queries)


def get_data_modeling_verification_queries(model_label: str) -> list[DuckLakeCopyVerificationQuery]:
    """Return the configured verification queries for the given model label."""
    config = _get_data_modeling_verification_config()
    return config.queries_for_model(model_label)


def get_data_imports_verification_queries(schema_name: str) -> list[DuckLakeCopyVerificationQuery]:
    """Return the configured verification queries for the given data imports schema."""
    config = _get_data_imports_verification_config()
    return config.queries_for_model(schema_name)


@functools.lru_cache
def _get_data_modeling_verification_config() -> DuckLakeVerificationConfig:
    raw = _load_verification_yaml("data_modeling.yaml")
    defaults = tuple(_parse_queries(raw.get("defaults", {}).get("queries")))
    model_overrides = {
        label: _ModelVerificationConfig(
            queries=tuple(_parse_queries(cfg.get("queries"))),
            inherit_defaults=cfg.get("inherit_defaults", True),
        )
        for label, cfg in (raw.get("models") or {}).items()
    }
    return DuckLakeVerificationConfig(default_queries=defaults, model_overrides=model_overrides)


@functools.lru_cache
def _get_data_imports_verification_config() -> DuckLakeVerificationConfig:
    raw = _load_verification_yaml("data_imports.yaml")
    defaults = tuple(_parse_queries(raw.get("defaults", {}).get("queries")))
    model_overrides = {
        label: _ModelVerificationConfig(
            queries=tuple(_parse_queries(cfg.get("queries"))),
            inherit_defaults=cfg.get("inherit_defaults", True),
        )
        for label, cfg in (raw.get("models") or {}).items()
    }
    return DuckLakeVerificationConfig(default_queries=defaults, model_overrides=model_overrides)


def _load_verification_yaml(filename: str) -> dict[str, Any]:
    path = Path(__file__).with_name(filename)
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_queries(raw_queries: Sequence[dict[str, Any]] | None) -> list[DuckLakeCopyVerificationQuery]:
    queries: list[DuckLakeCopyVerificationQuery] = []
    if not raw_queries:
        return queries

    for entry in raw_queries:
        name = entry.get("name")
        sql = entry.get("sql")
        if not name or not sql:
            raise ValueError("Verification queries must include both 'name' and 'sql' fields")

        description = entry.get("description")
        parameters = tuple(DuckLakeCopyVerificationParameter(param) for param in entry.get("parameters", []) or [])
        tolerance = float(entry.get("tolerance", 0.0) or 0.0)
        expected_value = float(entry.get("expected", 0.0) or 0.0)

        queries.append(
            DuckLakeCopyVerificationQuery(
                name=name,
                sql=sql.strip(),
                description=description,
                parameters=parameters,
                expected_value=expected_value,
                tolerance=tolerance,
            )
        )

    return queries


__all__ = [
    "DuckLakeCopyVerificationParameter",
    "DuckLakeCopyVerificationQuery",
    "DuckLakeVerificationConfig",
    "get_data_modeling_verification_queries",
    "get_data_imports_verification_queries",
]
