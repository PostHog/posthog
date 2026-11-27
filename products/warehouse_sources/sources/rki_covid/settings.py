from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import frozen

# The RKI COVID-19 API (api.corona-zahlen.org) is a public, unauthenticated JSON wrapper over
# published Robert Koch-Institut figures, maintained by Marlon Lückert. Every endpoint returns its
# full dataset in a single response — no pagination and no server-side timestamp cursor (history
# endpoints only take a relative `:days` window), so every table is full refresh only.
#
# Each endpoint returns a bespoke JSON shape, so endpoints are grouped by a `kind` that tells the
# transport how to reshape the response into flat rows:
#   snapshot      -> the response body is a single row (e.g. /germany)
#   data_snapshot -> body["data"] is a single row (e.g. /vaccinations)
#   dict_rows     -> body["data"] is a dict whose values are self-describing rows (e.g. /states)
#   keyed_rows    -> body["data"] is a dict whose keys carry the row identity and must be injected
#                    into each row under `key_field` (e.g. /germany/age-groups)
#   keyed_history -> body["data"] is a dict like keyed_rows, but each value nests its rows under
#                    "history"; each history row gets the key and the parent fields
#                    (e.g. /states/history/cases)
#   keyed_nested_rows -> body["data"] is a dict of dicts keyed by two levels; both keys are injected,
#                    under `key_field` and `nested_key_field` (e.g. /states/age-groups)
#   data_list     -> body["data"] is already a list of rows (e.g. /germany/history/cases)
#   data_history  -> the rows live at body["data"]["history"] (e.g. /germany/history/frozen-incidence)
ParseKind = Literal[
    "snapshot",
    "data_snapshot",
    "dict_rows",
    "keyed_rows",
    "keyed_history",
    "keyed_nested_rows",
    "data_list",
    "data_history",
]


NullColumnType = Literal["bigint", "double"]


@frozen
class RKICovidEndpointConfig:
    name: str
    path: str
    kind: ParseKind
    # Unique across the whole table. None for single-row snapshot tables that are replaced wholesale.
    primary_keys: Optional[list[str]]
    # Set for keyed_rows and keyed_history endpoints: the column the dict key is injected under.
    key_field: Optional[str] = None
    # Set for keyed_nested_rows endpoints: the column the inner dict key is injected under.
    nested_key_field: Optional[str] = None
    # A stable date column used for datetime partitioning. History rows are keyed by reporting day
    # and never move to another day, so `date` is safe. None for snapshot tables.
    partition_key: Optional[str] = None
    # Whether the endpoint accepts the optional `/:days` path suffix to trim the returned history
    # window server-side.
    supports_days: bool = False
    # Columns that are null in every row of a short history window. Null values are dropped from the
    # rows and the columns get these types, so they are not stored as text before values arrive.
    null_column_types: tuple[tuple[str, NullColumnType], ...] = ()
    description: Optional[str] = None


RKI_COVID_ENDPOINTS: dict[str, RKICovidEndpointConfig] = {
    "germany": RKICovidEndpointConfig(
        name="germany",
        path="/germany",
        kind="snapshot",
        primary_keys=None,
        description="Current nationwide COVID-19 snapshot for Germany: cumulative cases, deaths, recoveries, week incidence, R value, and hospitalization. One row, replaced on every sync.",
    ),
    "germany_age_groups": RKICovidEndpointConfig(
        name="germany_age_groups",
        path="/germany/age-groups",
        kind="keyed_rows",
        primary_keys=["age_group"],
        key_field="age_group",
        description="Nationwide cases, deaths, and hospitalization broken down by age group and sex. One row per age group. Full refresh.",
    ),
    "germany_history_cases": RKICovidEndpointConfig(
        name="germany_history_cases",
        path="/germany/history/cases",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily new reported COVID-19 cases for Germany. One row per day. Full refresh.",
    ),
    "germany_history_incidence": RKICovidEndpointConfig(
        name="germany_history_incidence",
        path="/germany/history/incidence",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily 7-day incidence per 100k inhabitants for Germany. One row per day. Full refresh.",
    ),
    "germany_history_deaths": RKICovidEndpointConfig(
        name="germany_history_deaths",
        path="/germany/history/deaths",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily new reported COVID-19 deaths for Germany. One row per day. Full refresh.",
    ),
    "germany_history_recovered": RKICovidEndpointConfig(
        name="germany_history_recovered",
        path="/germany/history/recovered",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily newly recovered COVID-19 cases for Germany. One row per day. Full refresh.",
    ),
    "germany_history_frozen_incidence": RKICovidEndpointConfig(
        name="germany_history_frozen_incidence",
        path="/germany/history/frozen-incidence",
        kind="data_history",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily 7-day incidence for Germany as originally published (not retroactively corrected). One row per day. Full refresh.",
    ),
    "germany_history_hospitalization": RKICovidEndpointConfig(
        name="germany_history_hospitalization",
        path="/germany/history/hospitalization",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily 7-day hospitalization cases and incidence for Germany, including reporting-delay adjusted values. One row per day. Full refresh.",
    ),
    "germany_history_r_value": RKICovidEndpointConfig(
        name="germany_history_r_value",
        path="/germany/history/rValue",
        kind="data_list",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily COVID-19 reproduction number (R value) estimates for Germany, as 4-day and 7-day values. One row per day. Full refresh. The series ends in June 2023, so leave the history window empty to import it.",
    ),
    "states": RKICovidEndpointConfig(
        name="states",
        path="/states",
        kind="dict_rows",
        primary_keys=["abbreviation"],
        description="Current COVID-19 snapshot per German federal state (Bundesland): cases, deaths, recoveries, week incidence, and hospitalization. One row per state. Full refresh.",
    ),
    "states_history_cases": RKICovidEndpointConfig(
        name="states_history_cases",
        path="/states/history/cases",
        kind="keyed_history",
        primary_keys=["abbreviation", "date"],
        key_field="abbreviation",
        partition_key="date",
        supports_days=True,
        description="Daily new reported COVID-19 cases per German federal state. One row per state and day. Full refresh.",
    ),
    "states_history_deaths": RKICovidEndpointConfig(
        name="states_history_deaths",
        path="/states/history/deaths",
        kind="keyed_history",
        primary_keys=["abbreviation", "date"],
        key_field="abbreviation",
        partition_key="date",
        supports_days=True,
        description="Daily new reported COVID-19 deaths per German federal state. One row per state and day. Full refresh.",
    ),
    "states_history_incidence": RKICovidEndpointConfig(
        name="states_history_incidence",
        path="/states/history/incidence",
        kind="keyed_history",
        primary_keys=["abbreviation", "date"],
        key_field="abbreviation",
        partition_key="date",
        supports_days=True,
        description="Daily 7-day incidence per 100k inhabitants per German federal state. One row per state and day. Full refresh.",
    ),
    "states_history_hospitalization": RKICovidEndpointConfig(
        name="states_history_hospitalization",
        path="/states/history/hospitalization",
        kind="keyed_history",
        primary_keys=["abbreviation", "date"],
        key_field="abbreviation",
        partition_key="date",
        supports_days=True,
        null_column_types=(
            ("adjustedCases7Days", "bigint"),
            ("adjustedLowerCases7Days", "bigint"),
            ("adjustedUpperCases7Days", "bigint"),
            ("adjustedIncidence7Days", "double"),
            ("adjustedLowerIncidence7Days", "double"),
            ("adjustedUpperIncidence7Days", "double"),
        ),
        description="Daily 7-day hospitalization cases and incidence per German federal state, including reporting-delay adjusted values. One row per state and day. Full refresh.",
    ),
    "states_age_groups": RKICovidEndpointConfig(
        name="states_age_groups",
        path="/states/age-groups",
        kind="keyed_nested_rows",
        primary_keys=["abbreviation", "age_group"],
        key_field="abbreviation",
        nested_key_field="age_group",
        description="Cases and deaths by sex, and hospitalization, per German federal state and age group. One row per state and age group. Full refresh.",
    ),
    "districts": RKICovidEndpointConfig(
        name="districts",
        path="/districts",
        kind="dict_rows",
        primary_keys=["ags"],
        description="Current COVID-19 snapshot per German district (Landkreis), keyed by the official municipality key (AGS). One row per district. Full refresh.",
    ),
    "districts_history_cases": RKICovidEndpointConfig(
        name="districts_history_cases",
        path="/districts/history/cases",
        kind="keyed_history",
        primary_keys=["ags", "date"],
        key_field="ags",
        partition_key="date",
        supports_days=True,
        description="Daily new reported COVID-19 cases per German district (Landkreis), keyed by AGS. One row per district and day. Full refresh.",
    ),
    "districts_history_incidence": RKICovidEndpointConfig(
        name="districts_history_incidence",
        path="/districts/history/incidence",
        kind="keyed_history",
        primary_keys=["ags", "date"],
        key_field="ags",
        partition_key="date",
        supports_days=True,
        description="Daily 7-day incidence per 100k inhabitants per German district (Landkreis), keyed by AGS. One row per district and day. Full refresh.",
    ),
    "districts_age_groups": RKICovidEndpointConfig(
        name="districts_age_groups",
        path="/districts/age-groups",
        kind="keyed_nested_rows",
        primary_keys=["ags", "age_group"],
        key_field="ags",
        nested_key_field="age_group",
        description="Cases and deaths per German district (Landkreis), keyed by AGS and broken down by age group and sex. One row per district and age group. Full refresh.",
    ),
    "testing_history": RKICovidEndpointConfig(
        name="testing_history",
        path="/testing/history",
        kind="data_history",
        primary_keys=["calendarWeek"],
        description="Weekly PCR testing figures for Germany: performed tests, positive tests, positivity rate, and reporting laboratories. One row per calendar week. Full refresh.",
    ),
    "vaccinations": RKICovidEndpointConfig(
        name="vaccinations",
        path="/vaccinations",
        kind="data_snapshot",
        primary_keys=None,
        description="Current nationwide COVID-19 vaccination totals for Germany: administered doses, vaccinated people per dose, doses per vaccine, and vaccination quotas. One row, replaced on every sync.",
    ),
    "vaccinations_history": RKICovidEndpointConfig(
        name="vaccinations_history",
        path="/vaccinations/history",
        kind="data_history",
        primary_keys=["date"],
        partition_key="date",
        supports_days=True,
        description="Daily COVID-19 vaccinations administered in Germany, split by first, second, and booster doses. One row per day. Full refresh.",
    ),
    "vaccinations_states": RKICovidEndpointConfig(
        name="vaccinations_states",
        path="/vaccinations/states",
        kind="keyed_rows",
        primary_keys=["abbreviation"],
        key_field="abbreviation",
        description="Current COVID-19 vaccination totals and quotas per German federal state. One row per state. Full refresh.",
    ),
}

ENDPOINTS = tuple(RKI_COVID_ENDPOINTS.keys())
