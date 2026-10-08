"""Which key an incremental sync merges on, and when that key has to be proven unique."""

from collections.abc import Iterable, Sequence


def resolve_merge_keys(
    persisted_keys: Sequence[str] | None,
    detected_keys: Sequence[str] | None,
    available_columns: Iterable[str],
) -> list[str] | None:
    """The key the merge will match rows on.

    A persisted key is the customer's own choice (or an earlier detection) and always wins, so the
    merge key stays stable across runs when live detection is flaky. `id` is the last resort, which
    is a guess rather than a constraint, so `should_probe_for_duplicates` treats it as unverified.

    Matched case-insensitively because engines like Snowflake uppercase unquoted identifiers, but
    the column's stored casing is returned: the merge indexes batches by the real name.
    """
    if persisted_keys:
        return list(persisted_keys)
    if detected_keys:
        return list(detected_keys)
    id_column = next((name for name in available_columns if name.lower() == "id"), None)
    return [id_column] if id_column is not None else None


def should_probe_for_duplicates(
    merge_keys: Sequence[str] | None,
    declared_keys: Sequence[str] | None,
    *,
    constraints_enforced: bool,
) -> bool:
    """Whether the merge key still has to be proven unique against the source.

    Only one thing makes a probe unnecessary: the engine enforces the constraint the key comes
    from. A key the customer picked, and the `id` guess, carry no such guarantee on any engine, and
    on an engine that records constraints without enforcing them (Redshift, BigQuery, ClickHouse)
    neither does a declared one.
    """
    if not merge_keys:
        return False
    if not constraints_enforced or not declared_keys:
        return True
    return list(merge_keys) != list(declared_keys)


def needs_full_probe(merge_keys: Sequence[str], verified_keys: Sequence[str] | None) -> bool:
    """Whether this run has to scan the whole table rather than the rows it is about to read.

    A key is proven once: scanning the whole table on every run costs a full GROUP BY per sync,
    which on a large table outlives the statement timeout. Afterwards each run only has to prove
    the rows it brings in, because a duplicate among those is what a merge cannot resolve. A key
    that was never proven, or one that replaced the proven key, starts again from the whole table.
    """
    return list(merge_keys) != list(verified_keys or [])
