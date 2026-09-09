"""Query guidance for Apple's restated analytics report streams.

Apple restates each analytics report date for about six days: every daily instance
republishes recent report dates in full, and the sync keeps each instance's rows under
their own ``processing_date`` (the streams key on app, processing date and file line).
One report date therefore accumulates several vintages, and a naive
``SUM ... GROUP BY date`` overcounts severalfold without any error.

The source cannot resolve this in the data itself. The warehouse-source framework has no
hook for a source to ship a companion view, and the pipeline's merge only touches the
primary keys present in an arriving batch, so rows written earlier (superseded vintages,
or the one-time snapshot backfill) can never be re-flagged: an ``is_latest_restatement``
column would silently go stale on the next restatement. What the source can do in-module
is document the resolution exactly, per stream. Everything here derives from the endpoint
catalog in ``settings.py`` and the column catalog in ``canonical_descriptions.py``, so
analytics streams added to the catalog later are covered without code changes.
"""

from collections.abc import Mapping

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    AppStoreConnectEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ANALYTICS_KIND = "analytics_report"

# The measure columns across Apple's analytics reports: the columns consumers sum, which take
# the argMax in the deduplicating query; every other documented column is a grouping dimension.
# This is Apple's column vocabulary, not a list of stream names, so a new stream built from the
# same columns needs no code change here. A stream with no recognized measure falls back to the
# latest-vintage join recipe: guessing the split would group by a measure and silently keep one
# row per vintage.
_MEASURE_COLUMNS: frozenset[str] = frozenset(
    {
        "sessions",
        "total_session_duration",
        "unique_devices",
        "counts",
        "unique_counts",
        "crashes",
        "pre_orders_placed",
        "pre_orders_canceled",
    }
)

# Apple includes the report date in every analytics report as `date`; restatements always
# supersede whole report dates within an app.
_REPORT_DATE_COLUMN = "date"

# Mirrors `pipelines.helpers.build_table_name`, whose physical name is the source's optional
# user-set table prefix followed by this one. Naming the table wrongly fails silently rather than
# loudly: a second App Store Connect source is forced to take a prefix, so the unprefixed name
# resolves to the first source's table instead of erroring.
_TABLE_NAME_PREFIX = f"{ExternalDataSourceType.APPSTORECONNECT.value}_".lower()

# Shown only where the guidance is built without a source in hand (the public docs endpoint and the
# source caption), so the prefix is unknowable rather than known to be empty.
_TABLE_PREFIX_NOTE = (
    "This query names the table as connected without a table name prefix; if you set one, add it "
    "wherever the table name appears."
)

_MEASURE_GUIDANCE = (
    "Kept for every restatement of a report date; aggregate only the latest restatement (see the table description)."
)


def analytics_stream_names(endpoints: Mapping[str, AppStoreConnectEndpointConfig]) -> tuple[str, ...]:
    """Names of the streams that carry restated analytics report data, from the catalog."""
    return tuple(name for name, config in endpoints.items() if config.kind == _ANALYTICS_KIND)


@frozen
class RestatementRecipe:
    """The query that returns one row per report date and dimension tuple for one stream."""

    stream: str
    table_name: str
    # The column whose highest value per app and report date marks the current vintage.
    vintage_column: str
    # Grouping columns of the argMax form; empty for the latest-vintage join form.
    dimensions: tuple[str, ...]
    # Measure columns resolved with argMax; empty for the latest-vintage join form.
    measures: tuple[str, ...]
    sql: str

    @property
    def sql_single_line(self) -> str:
        return " ".join(self.sql.split())


def _vintage_column(config: AppStoreConnectEndpointConfig) -> str | None:
    # The incremental field that is also part of the primary key: each restatement arrives as
    # new rows under a new value of it.
    for field in config.incremental_fields:
        name = field.get("field")
        if name and name in config.primary_keys:
            return name
    return None


def _identity_keys(config: AppStoreConnectEndpointConfig, vintage_column: str) -> list[str]:
    # Primary keys minus the vintage and the parser's synthetic file-position keys (underscore
    # prefixed, like `_line`): what identifies the entity across vintages, e.g. the app.
    return [key for key in config.primary_keys if key != vintage_column and not key.startswith("_")]


def _latest_vintage_join(table_name: str, identity_keys: list[str], vintage_column: str) -> str:
    # Restricts the table to the newest restatement of each report date. A restatement
    # republishes its report date in full, so a dimension tuple the newest one omits is gone
    # rather than unchanged: reading a value for it from an older vintage would resurrect it.
    keys = [*identity_keys, _REPORT_DATE_COLUMN]
    key_list = ", ".join(keys)
    conditions = " AND ".join(f"raw.{key} = latest.{key}" for key in [*keys, vintage_column])
    return (
        f"FROM {table_name} AS raw\n"
        "INNER JOIN (\n"
        f"    SELECT {key_list}, max({vintage_column}) AS {vintage_column}\n"
        f"    FROM {table_name}\n"
        f"    GROUP BY {key_list}\n"
        ") AS latest\n"
        f"    ON {conditions}"
    )


def _latest_vintage_sql(table_name: str, identity_keys: list[str], vintage_column: str) -> str:
    return f"SELECT raw.*\n{_latest_vintage_join(table_name, identity_keys, vintage_column)}"


def restatement_recipe(
    config: AppStoreConnectEndpointConfig, columns: Mapping[str, str], table_prefix: str = ""
) -> RestatementRecipe | None:
    """Build the stream's deduplicating query from its catalog entry and documented columns.

    Prefers the argMax form (one row per report date and dimension tuple, each measure taken
    from the latest vintage). Falls back to the latest-vintage join (the newest restatement of
    each report date, whole) when the documented columns can't be split into dimensions and
    measures. ``None`` for streams whose catalog entry carries no vintage key to dedup on.

    ``table_prefix`` is the connected source's user-set table prefix, so the query names the
    table the reader actually has.
    """
    if config.kind != _ANALYTICS_KIND:
        return None
    vintage_column = _vintage_column(config)
    if vintage_column is None:
        return None

    table_name = f"{table_prefix}{_TABLE_NAME_PREFIX}{config.name}"
    excluded = {vintage_column, *(key for key in config.primary_keys if key.startswith("_"))}
    names = [name for name in columns if name not in excluded]
    measures = tuple(name for name in names if name in _MEASURE_COLUMNS)
    dimensions = tuple(name for name in names if name not in _MEASURE_COLUMNS)
    if _REPORT_DATE_COLUMN in dimensions:
        dimensions = (_REPORT_DATE_COLUMN, *(name for name in dimensions if name != _REPORT_DATE_COLUMN))

    if not measures or _REPORT_DATE_COLUMN not in dimensions:
        return RestatementRecipe(
            stream=config.name,
            table_name=table_name,
            vintage_column=vintage_column,
            dimensions=(),
            measures=(),
            sql=_latest_vintage_sql(table_name, _identity_keys(config, vintage_column), vintage_column),
        )

    select_lines = [
        *(f"raw.{dimension}" for dimension in dimensions),
        *(f"argMax(raw.{measure}, raw.{vintage_column}) AS {measure}" for measure in measures),
    ]
    select_body = ",\n    ".join(select_lines)
    group_body = ",\n    ".join(f"raw.{dimension}" for dimension in dimensions)
    join_body = _latest_vintage_join(table_name, _identity_keys(config, vintage_column), vintage_column)
    sql = f"SELECT\n    {select_body}\n{join_body}\nGROUP BY\n    {group_body}"
    return RestatementRecipe(
        stream=config.name,
        table_name=table_name,
        vintage_column=vintage_column,
        dimensions=dimensions,
        measures=measures,
        sql=sql,
    )


def _table_guidance(recipe: RestatementRecipe, prefix_known: bool) -> str:
    warning = (
        f"Apple restates each report date for about six days, and every restatement is kept as new "
        f"rows with a later {recipe.vintage_column}, so summing raw rows overcounts."
    )
    if recipe.measures:
        resolution = "Get one row per report date and dimension combination with"
    else:
        resolution = "Keep only the latest restatement of each report date with"
    guidance = f"{warning} {resolution}: {recipe.sql_single_line}"
    return guidance if prefix_known else f"{guidance} {_TABLE_PREFIX_NOTE}"


def _vintage_column_guidance(vintage_column: str) -> str:
    return (
        f"The rows with the highest {vintage_column} for an app and report date are the current "
        "restatement; see the table description for the deduplicating query."
    )


def with_restatement_guidance(
    descriptions: Mapping[str, CanonicalEndpoint],
    endpoints: Mapping[str, AppStoreConnectEndpointConfig] = APP_STORE_CONNECT_ENDPOINTS,
    table_prefix: str | None = None,
) -> CanonicalDescriptions:
    """A copy of ``descriptions`` where every analytics stream in the catalog documents its dedup.

    Applied at read time (`AppStoreConnectSource.get_canonical_descriptions`) rather than baked
    into the ``CANONICAL_DESCRIPTIONS`` literal, so entries other code derives from stay pristine
    and streams are covered regardless of where in the module their entry is added. Idempotent:
    guidance already present is never appended twice.

    ``table_prefix`` is the connected source's user-set prefix, so the queries name the reader's
    own table. ``None`` means no source was in hand (the public docs endpoint, which describes the
    source generically); the queries then name the unprefixed table and say so.
    """
    result: CanonicalDescriptions = dict(descriptions)
    for name in analytics_stream_names(endpoints):
        existing = result.get(name)
        entry: CanonicalEndpoint = existing.copy() if existing is not None else {}
        columns = dict(entry.get("columns") or {})
        recipe = restatement_recipe(endpoints[name], columns, table_prefix or "")
        if recipe is None:
            continue

        guidance = _table_guidance(recipe, prefix_known=table_prefix is not None)
        description = (entry.get("description") or "").strip()
        if guidance not in description:
            entry["description"] = f"{description} {guidance}".strip()

        vintage_note = _vintage_column_guidance(recipe.vintage_column)
        if recipe.vintage_column in columns and vintage_note not in columns[recipe.vintage_column]:
            columns[recipe.vintage_column] = f"{columns[recipe.vintage_column].rstrip()} {vintage_note}"
        for measure in recipe.measures:
            if _MEASURE_GUIDANCE not in columns[measure]:
                columns[measure] = f"{columns[measure].rstrip()} {_MEASURE_GUIDANCE}"
        if columns:
            entry["columns"] = columns
        result[name] = entry
    return result


def restatement_caption(
    endpoints: Mapping[str, AppStoreConnectEndpointConfig] = APP_STORE_CONNECT_ENDPOINTS,
    descriptions: Mapping[str, CanonicalEndpoint] = CANONICAL_DESCRIPTIONS,
) -> str:
    """Markdown section for the source caption documenting the analytics restatement dedup.

    Carries the exact query for the catalog's first analytics stream with a full argMax recipe,
    so the caption stays true to whatever streams the catalog ships.
    """
    example: RestatementRecipe | None = None
    for name in analytics_stream_names(endpoints):
        entry = descriptions.get(name) or {}
        recipe = restatement_recipe(endpoints[name], entry.get("columns") or {})
        if recipe is None:
            continue
        if recipe.measures:
            example = recipe
            break
        example = example or recipe
    if example is None:
        return ""
    return (
        "Analytics report tables keep every restatement Apple publishes for a report date (about six "
        "days of revisions), so a raw `SUM` grouped by date overcounts. The raw rows preserve the "
        "restatement history; to aggregate, keep only the latest restatement per report date and "
        "dimension combination, for example:\n"
        "\n"
        f"```\n{example.sql}\n```\n"
        "\n"
        f"{_TABLE_PREFIX_NOTE} Each analytics table's description carries the exact query for that table."
    )
