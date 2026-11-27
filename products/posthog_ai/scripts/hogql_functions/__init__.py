from __future__ import annotations


def hogql_functions() -> list[str]:
    """Return sorted list of all public HogQL function names.

    Excludes underscore-prefixed internals, UDFs, and *If combinator variants
    (e.g. countIf, sumIf) where the base function also exists.
    """
    from posthog.hogql.functions.aggregations import HOGQL_AGGREGATIONS
    from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS
    from posthog.hogql.functions.udfs import UDFS

    all_names: set[str] = set()
    for name in HOGQL_CLICKHOUSE_FUNCTIONS:
        if not name.startswith("_") and name not in UDFS:
            all_names.add(name)
    for name in HOGQL_AGGREGATIONS:
        if not name.startswith("_"):
            all_names.add(name)

    def _is_if_combinator(name: str) -> bool:
        return name.endswith("If") and name[:-2] in all_names

    # Names that differ only in case (MD5, md5) tie under str.lower and would keep set order, which
    # changes with the hash seed. The rendered skills must be byte-identical across builds, because
    # the eval sandbox image is cached by their content.
    return sorted((n for n in all_names if not _is_if_combinator(n)), key=lambda name: (name.lower(), name))
