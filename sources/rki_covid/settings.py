import dataclasses
from typing import Literal, Optional

# The RKI COVID-19 API (api.corona-zahlen.org) is a public, unauthenticated JSON wrapper over
# published Robert Koch-Institut figures, maintained by Marlon Lückert. Every endpoint returns its
# full dataset in a single response — no pagination and no server-side timestamp cursor (history
# endpoints only take a relative `:days` window), so every table is full refresh only.
#
# Each endpoint returns a bespoke JSON shape, so endpoints are grouped by a `kind` that tells the
# transport how to reshape the response into flat rows:
#   snapshot     -> the response body is a single row (e.g. /germany)
#   dict_rows    -> body["data"] is a dict whose values are self-describing rows (e.g. /states)
#   keyed_rows   -> body["data"] is a dict whose keys carry the row identity and must be injected
#                   into each row under `key_field` (e.g. /germany/age-groups)
#   data_list    -> body["data"] is already a list of rows (e.g. /germany/history/cases)
#   data_history -> the rows live at body["data"]["history"] (e.g. /germany/history/frozen-incidence)
ParseKind = Literal["snapshot", "dict_rows", "keyed_rows", "data_list", "data_history"]


@dataclasses.dataclass
class RKICovidEndpointConfig:
    name: str
    path: str
    kind: ParseKind
    # Unique across the whole table. None for single-row snapshot tables that are replaced wholesale.
    primary_keys: Optional[list[str]]
    # Set for keyed_rows endpoints: the column the dict key is injected under.
    key_field: Optional[str] = None
    # A stable date column used for datetime partitioning. History rows are keyed by reporting day
    # and never move to another day, so `date` is safe. None for snapshot tables.
    partition_key: Optional[str] = None
    # Whether the endpoint accepts the optional `/:days` path suffix to trim the returned history
    # window server-side.
    supports_days: bool = False
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
    "states": RKICovidEndpointConfig(
        name="states",
        path="/states",
        kind="dict_rows",
        primary_keys=["abbreviation"],
        description="Current COVID-19 snapshot per German federal state (Bundesland): cases, deaths, recoveries, week incidence, and hospitalization. One row per state. Full refresh.",
    ),
    "districts": RKICovidEndpointConfig(
        name="districts",
        path="/districts",
        kind="dict_rows",
        primary_keys=["ags"],
        description="Current COVID-19 snapshot per German district (Landkreis), keyed by the official municipality key (AGS). One row per district. Full refresh.",
    ),
    "testing_history": RKICovidEndpointConfig(
        name="testing_history",
        path="/testing/history",
        kind="data_history",
        primary_keys=["calendarWeek"],
        description="Weekly PCR testing figures for Germany: performed tests, positive tests, positivity rate, and reporting laboratories. One row per calendar week. Full refresh.",
    ),
}

ENDPOINTS = tuple(RKI_COVID_ENDPOINTS.keys())
