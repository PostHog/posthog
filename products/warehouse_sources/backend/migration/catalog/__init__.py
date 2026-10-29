"""Matches a vendor's connectors, tables and settings to PostHog sources.

Matching runs on every call against the live source registry, so a new PostHog source or table
matches without a code change. Vendor files such as `fivetran.py` hold only the exceptions.
"""

import re
import functools
from collections.abc import Collection, Iterable, Mapping
from enum import StrEnum
from typing import Any

import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldSSHTunnelConfig
from products.warehouse_sources.backend.migration.catalog import fivetran
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@frozen
class _Provider:
    source_overrides: Mapping[str, ExternalDataSourceType]
    rejected_sources: Collection[str]
    table_suffix_rewrites: tuple[tuple[str, str], ...]
    tunnel_config_keys: Mapping[str, str]
    config_key_overrides: Mapping[ExternalDataSourceType, Mapping[str, str]]
    destination_types: Mapping[str, ExternalDataDestination.Type]


_PROVIDERS: Mapping[str, _Provider] = {
    "fivetran": _Provider(
        source_overrides=fivetran.SOURCE_OVERRIDES,
        rejected_sources=fivetran.REJECTED_SOURCES,
        table_suffix_rewrites=fivetran.TABLE_SUFFIX_REWRITES,
        tunnel_config_keys=fivetran.TUNNEL_CONFIG_KEYS,
        config_key_overrides=fivetran.CONFIG_KEY_OVERRIDES,
        destination_types=fivetran.DESTINATION_TYPES,
    )
}


class MatchConfidence(StrEnum):
    # The names are the same apart from case and separators.
    EXACT = "exact"
    # A naming rule paired them, so the user should confirm the pair.
    INFERRED = "inferred"


@frozen
class TableMatch:
    vendor_table: str
    # None when no PostHog table matches. The agent can propose one from `posthog_tables`.
    posthog_table: str | None
    confidence: MatchConfidence | None


@frozen
class PostHogTables:
    names: frozenset[str]
    # False when the source also syncs tables it discovers in the user's account, such as Firebase
    # collections. An unmatched vendor table can then still exist under its own name.
    complete: bool


def _letters(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@functools.cache
def _source_types_by_letters() -> Mapping[str, ExternalDataSourceType]:
    return {_letters(source_type.value): source_type for source_type in ExternalDataSourceType}


def match_source(provider: str, vendor_service: str) -> ExternalDataSourceType | None:
    # Unreleased sources match too, so the caller can tell a planned source from a missing one.
    rules = _PROVIDERS[provider]
    if vendor_service in rules.rejected_sources:
        source_type = None
    else:
        source_type = rules.source_overrides.get(vendor_service) or _source_types_by_letters().get(
            _letters(vendor_service)
        )
    if source_type is None:
        logger.info("warehouse_migration_unmatched_source", provider=provider, vendor_service=vendor_service)
    return source_type


def match_destination(provider: str, vendor_service: str) -> ExternalDataDestination.Type | None:
    return _PROVIDERS[provider].destination_types.get(vendor_service)


def posthog_tables(source_type: ExternalDataSourceType) -> PostHogTables | None:
    """Tables the source can sync, or None when the user defines them all, as in a database."""
    source = SourceRegistry.get_source(source_type)
    if source.lists_tables_without_credentials:
        documented = frozenset(table["name"] for table in source.get_documented_tables())
        if documented:
            return PostHogTables(names=documented, complete=True)
    # A source that cannot list its tables without credentials or config still describes the
    # tables it always has, but it can discover more in the user's account.
    described = frozenset(source.get_canonical_descriptions())
    return PostHogTables(names=described, complete=False) if described else None


def _inferred_keys(vendor_table: str, rewrites: tuple[tuple[str, str], ...]) -> list[str]:
    stems = [vendor_table] + [
        vendor_table.removesuffix(suffix) + replacement
        for suffix, replacement in rewrites
        if vendor_table.endswith(suffix)
    ]
    keys: list[str] = []
    for stem in (_letters(s) for s in stems if s):
        keys += [stem, f"{stem}s", f"{stem}es"]
        if stem.endswith("y"):
            keys.append(f"{stem[:-1]}ies")
        if stem.endswith("s"):
            keys.append(stem[:-1])
    return keys


def match_tables(
    provider: str, vendor_tables: Iterable[str], posthog_table_names: Collection[str]
) -> tuple[TableMatch, ...]:
    rewrites = _PROVIDERS[provider].table_suffix_rewrites
    by_letters: dict[str, str] = {}
    for name in sorted(posthog_table_names):
        by_letters.setdefault(_letters(name), name)

    vendor_tables = list(vendor_tables)
    exact = {t: by_letters[_letters(t)] for t in vendor_tables if _letters(t) in by_letters}
    taken = set(exact.values())
    # A table another vendor table matches exactly is taken. Salesforce `account_history` is a
    # field audit log, not the `Account` records that `account` already holds.
    inferred: dict[str, tuple[str, int]] = {}
    for vendor_table in vendor_tables:
        if vendor_table in exact:
            continue
        keys = _inferred_keys(vendor_table, rewrites)
        hit = next(
            ((by_letters[k], rank) for rank, k in enumerate(keys) if k in by_letters and by_letters[k] not in taken),
            None,
        )
        if hit is not None:
            inferred[vendor_table] = hit
    # When two vendor tables infer the same PostHog table, the one whose name needed the smaller
    # change keeps it, so `campaign` beats `campaign_history` for `campaigns`. The name breaks ties,
    # so the result does not depend on the input order.
    winners: dict[str, str] = {}
    for vendor_table, (target, _rank) in sorted(inferred.items(), key=lambda item: (item[1][1], item[0])):
        winners.setdefault(target, vendor_table)

    matches: list[TableMatch] = []
    for vendor_table in vendor_tables:
        if vendor_table in exact:
            matches.append(
                TableMatch(
                    vendor_table=vendor_table, posthog_table=exact[vendor_table], confidence=MatchConfidence.EXACT
                )
            )
        elif vendor_table in inferred and winners[inferred[vendor_table][0]] == vendor_table:
            matches.append(
                TableMatch(
                    vendor_table=vendor_table,
                    posthog_table=inferred[vendor_table][0],
                    confidence=MatchConfidence.INFERRED,
                )
            )
        else:
            matches.append(TableMatch(vendor_table=vendor_table, posthog_table=None, confidence=None))
    unmatched = [m.vendor_table for m in matches if m.posthog_table is None]
    if unmatched:
        logger.info("warehouse_migration_unmatched_tables", provider=provider, vendor_tables=unmatched)
    return tuple(matches)


def prefill_config(
    provider: str, source_type: ExternalDataSourceType, vendor_config: Mapping[str, Any]
) -> dict[str, Any]:
    """Non-secret source settings keyed by PostHog payload path. A dot is a nested field."""
    rules = _PROVIDERS[provider]
    fields = SourceRegistry.get_source(source_type).get_source_config.fields
    key_map = {
        field.name: field.name for field in fields if isinstance(field, SourceFieldInputConfig) and not field.secret
    }
    if any(isinstance(field, SourceFieldSSHTunnelConfig) for field in fields):
        key_map.update(rules.tunnel_config_keys)
    key_map.update(rules.config_key_overrides.get(source_type, {}))
    return {
        posthog_key: vendor_config[vendor_key]
        for vendor_key, posthog_key in key_map.items()
        if vendor_config.get(vendor_key) not in (None, "")
    }
