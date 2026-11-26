from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.rki_covid._config import RKICovidSourceConfig
from products.warehouse_sources.sources.rki_covid.rki_covid import (
    ROW_BATCH_SIZE,
    RKICovidAPIError,
    build_url,
    validate_connection,
)
from products.warehouse_sources.sources.rki_covid.settings import RKI_COVID_ENDPOINTS
from products.warehouse_sources.sources.rki_covid.source import RKICovidSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)


def _ok(body: Any = None, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body if body is not None else {})


def _run(endpoint: str, script: Script, history_days: int | None = None) -> DriveResult:
    return SourceDriver(RKICovidSource(), RKICovidSourceConfig(history_days=history_days)).run(endpoint, script)


class TestRKICovid:
    @parameterized.expand(
        [
            (
                "history_with_days",
                "germany_history_cases",
                30,
                "https://api.corona-zahlen.org/germany/history/cases/30",
            ),
            (
                "history_without_days",
                "germany_history_cases",
                None,
                "https://api.corona-zahlen.org/germany/history/cases",
            ),
            # Non-history endpoints must never grow a days suffix, even when the user configured one.
            ("snapshot_ignores_days", "states", 30, "https://api.corona-zahlen.org/states"),
        ]
    )
    def test_build_url_applies_days_only_where_supported(
        self, _name: str, endpoint: str, days: int | None, expected: str
    ) -> None:
        assert build_url(RKI_COVID_ENDPOINTS[endpoint], days) == expected

    def test_fetch_raises_on_error_envelope(self) -> None:
        # The API signals some failures with HTTP 200 and an `error` body.
        result = _run("germany", [_ok({"error": {"message": "wrong route"}})])
        assert isinstance(result.raised, RKICovidAPIError)
        assert "error_response" in str(result.raised)

    def test_fetch_raises_on_non_dict_body(self) -> None:
        result = _run("germany", [_ok(["unexpected"])])
        assert isinstance(result.raised, RKICovidAPIError)
        assert "unexpected_response" in str(result.raised)

    def test_fetch_raises_on_http_error(self) -> None:
        result = _run("germany", [_ok(status=404)])
        assert isinstance(result.raised, requests.HTTPError)

    def test_germany_snapshot_yields_single_row(self) -> None:
        body = {"cases": 100, "deaths": 5, "meta": {"lastUpdate": "2026-07-21T05:35:57.000Z"}}
        assert _run("germany", [_ok(body)]).rows == [body]

    def test_age_groups_inject_dict_key_as_age_group_column(self) -> None:
        # The age band only exists as the dict key; dropping it would leave rows with no identity.
        body = {
            "data": {
                "A00-A04": {"casesMale": 1, "casesFemale": 2},
                "A80+": {"casesMale": 3, "casesFemale": 4},
            },
            "meta": {},
        }
        assert _run("germany_age_groups", [_ok(body)]).rows == [
            {"age_group": "A00-A04", "casesMale": 1, "casesFemale": 2},
            {"age_group": "A80+", "casesMale": 3, "casesFemale": 4},
        ]

    @parameterized.expand(
        [
            ("states", "states_age_groups", "abbreviation", "SH", "BY"),
            ("districts", "districts_age_groups", "ags", "01001", "09162"),
        ]
    )
    def test_nested_age_groups_inject_entity_and_age_group_keys(
        self, _name: str, endpoint: str, key_field: str, first_key: str, second_key: str
    ) -> None:
        # Every entity reports the same age bands, so rows only stay unique with both dict keys injected.
        body = {
            "data": {
                first_key: {
                    "A00-A04": {"casesMale": 1, "hospitalization": {"cases7Days": 0}},
                    "A80+": {"casesMale": 2},
                },
                second_key: {"A00-A04": {"casesMale": 3}, "unexpected": "not a row"},
                "broken": ["not", "a", "dict"],
            },
            "meta": {},
        }
        result = _run(endpoint, [_ok(body)], history_days=30)
        assert result.paths == [RKI_COVID_ENDPOINTS[endpoint].path]
        assert result.response is not None
        assert result.response.primary_keys == [key_field, "age_group"]
        assert result.rows == [
            {key_field: first_key, "age_group": "A00-A04", "casesMale": 1, "hospitalization": {"cases7Days": 0}},
            {key_field: first_key, "age_group": "A80+", "casesMale": 2},
            {key_field: second_key, "age_group": "A00-A04", "casesMale": 3},
        ]

    def test_vaccinations_snapshot_drops_per_state_figures_and_keeps_meta(self) -> None:
        # The per-state figures belong to vaccinations_states; keeping them would nest 17 states into one cell.
        body = {
            "data": {"vaccinated": 10, "quote": 0.5, "states": {"BY": {"vaccinated": 3}}},
            "meta": {"lastUpdate": "2024-07-09T07:00:22.000Z"},
        }
        assert _run("vaccinations", [_ok(body)]).rows == [
            {"vaccinated": 10, "quote": 0.5, "meta": {"lastUpdate": "2024-07-09T07:00:22.000Z"}}
        ]

    def test_states_history_flattens_each_state_history_with_state_identity(self) -> None:
        # History rows only carry date and cases; without the state key they collide on the primary key.
        body = {
            "data": {
                "SH": {"id": 1, "name": "Schleswig-Holstein", "history": [{"cases": 4, "date": "2026-07-19"}]},
                "BY": {
                    "id": 9,
                    "name": "Bayern",
                    "history": [{"cases": 1, "date": "2026-07-19"}, {"cases": 2, "date": "2026-07-20"}],
                },
            },
            "meta": {},
        }
        result = _run("states_history_cases", [_ok(body)], history_days=30)
        assert result.paths == ["/states/history/cases/30"]
        assert result.rows == [
            {"abbreviation": "SH", "id": 1, "name": "Schleswig-Holstein", "cases": 4, "date": "2026-07-19"},
            {"abbreviation": "BY", "id": 9, "name": "Bayern", "cases": 1, "date": "2026-07-19"},
            {"abbreviation": "BY", "id": 9, "name": "Bayern", "cases": 2, "date": "2026-07-20"},
        ]

    @parameterized.expand(
        [
            ("states_deaths", "states_history_deaths", "abbreviation", "SH", "BY", "deaths"),
            ("states_incidence", "states_history_incidence", "abbreviation", "SH", "BY", "weekIncidence"),
            ("districts_cases", "districts_history_cases", "ags", "01001", "09162", "cases"),
            ("districts_incidence", "districts_history_incidence", "ags", "01001", "09162", "weekIncidence"),
            ("states_hospitalization", "states_history_hospitalization", "abbreviation", "SH", "BY", "cases7Days"),
        ]
    )
    def test_keyed_history_endpoints_request_their_path_and_key_rows_by_entity_and_day(
        self, _name: str, endpoint: str, key_field: str, first_key: str, second_key: str, value_field: str
    ) -> None:
        # Both entities report the same day, so rows only stay unique if the entity key is injected.
        body = {
            "data": {
                first_key: {"name": "first", "history": [{value_field: 1, "date": "2026-07-19T00:00:00.000Z"}]},
                second_key: {"name": "second", "history": [{value_field: 2, "date": "2026-07-19T00:00:00.000Z"}]},
            },
            "meta": {},
        }
        result = _run(endpoint, [_ok(body)], history_days=7)
        assert result.paths == [f"{RKI_COVID_ENDPOINTS[endpoint].path}/7"]
        assert result.response is not None
        assert result.response.primary_keys == [key_field, "date"]
        assert result.rows == [
            {key_field: first_key, "name": "first", value_field: 1, "date": "2026-07-19T00:00:00.000Z"},
            {key_field: second_key, "name": "second", value_field: 2, "date": "2026-07-19T00:00:00.000Z"},
        ]

    @parameterized.expand([("all_null", None, None), ("with_values", 283, 9.74)])
    def test_states_hospitalization_types_nowcast_columns_independent_of_window(
        self, _name: str, adjusted_cases: int | None, adjusted_incidence: float | None
    ) -> None:
        # A short window returns only null nowcasts; an untyped null column would be stored as text,
        # and the column type must not depend on whether the first sync saw values.
        body = {
            "data": {
                "SH": {
                    "name": "Schleswig-Holstein",
                    "history": [
                        {
                            "cases7Days": 4,
                            "adjustedCases7Days": adjusted_cases,
                            "adjustedIncidence7Days": adjusted_incidence,
                            "date": "2026-07-19",
                        },
                        {"cases7Days": 5, "adjustedCases7Days": None, "date": "2026-07-20"},
                    ],
                },
            },
            "meta": {},
        }
        result = _run("states_history_hospitalization", [_ok(body)], history_days=3)
        assert result.response is not None
        assert result.response.column_hints is not None
        assert result.response.column_hints["adjustedCases7Days"] == "bigint"
        assert result.response.column_hints["adjustedIncidence7Days"] == "double"
        first_row: dict[str, Any] = {
            "abbreviation": "SH",
            "name": "Schleswig-Holstein",
            "cases7Days": 4,
            "date": "2026-07-19",
        }
        if adjusted_cases is not None:
            first_row["adjustedCases7Days"] = adjusted_cases
            first_row["adjustedIncidence7Days"] = adjusted_incidence
        assert result.rows == [
            first_row,
            {"abbreviation": "SH", "name": "Schleswig-Holstein", "cases7Days": 5, "date": "2026-07-20"},
        ]

    def test_large_responses_are_yielded_in_bounded_batches_without_losing_rows(self) -> None:
        districts = {
            f"{n:05d}": {
                "ags": f"{n:05d}",
                "history": [{"cases": n, "date": f"2026-07-{day:02d}"} for day in (1, 2, 3)],
            }
            for n in range(ROW_BATCH_SIZE)
        }
        result = _run("districts_history_cases", [_ok({"data": districts, "meta": {}})])
        assert [len(batch) for batch in result.items] == [ROW_BATCH_SIZE, ROW_BATCH_SIZE, ROW_BATCH_SIZE]
        assert len({(row["ags"], row["date"]) for row in result.rows}) == 3 * ROW_BATCH_SIZE

    def test_states_yield_one_row_per_dict_value(self) -> None:
        body = {
            "data": {
                "SH": {"id": 1, "abbreviation": "SH", "name": "Schleswig-Holstein", "cases": 10},
                "HH": {"id": 2, "abbreviation": "HH", "name": "Hamburg", "cases": 20},
            },
            "meta": {},
        }
        assert [r["abbreviation"] for r in _run("states", [_ok(body)]).rows] == ["SH", "HH"]

    def test_history_list_yields_data_rows(self) -> None:
        body = {
            "data": [
                {"cases": 0, "date": "2026-07-18T00:00:00.000Z"},
                {"cases": 7, "date": "2026-07-20T00:00:00.000Z"},
            ],
            "meta": {},
        }
        assert _run("germany_history_cases", [_ok(body)]).rows == body["data"]

    @parameterized.expand(
        [
            ("cases", "germany_history_cases", "/germany/history/cases/30"),
            ("r_value", "germany_history_r_value", "/germany/history/rValue/30"),
        ]
    )
    def test_history_days_adds_a_days_suffix_to_the_request(self, _name: str, endpoint: str, path: str) -> None:
        result = _run(endpoint, [_ok({"data": [], "meta": {}})], history_days=30)
        assert result.paths == [path]

    def test_r_value_history_keeps_rows_with_only_one_estimate(self) -> None:
        # The API reports only the 7-day value early on and only the 4-day value at the end of the series.
        body = {
            "data": [
                {"rValue7Days": 1.1, "date": "2021-03-01T00:00:00.000Z"},
                {"rValue7Days": 0.9, "rValue4Days": 0.8, "date": "2021-03-02T00:00:00.000Z"},
                {"rValue4Days": 0.7, "date": "2021-03-03T00:00:00.000Z"},
            ],
            "meta": {},
        }
        assert _run("germany_history_r_value", [_ok(body)]).rows == body["data"]

    @parameterized.expand(
        [
            (
                "frozen_incidence",
                "germany_history_frozen_incidence",
                {
                    "data": {
                        "abbreviation": "Bund",
                        "name": "Bundesgebiet",
                        "history": [{"date": "2026-07-19T00:00:00.000Z", "weekIncidence": 0.07}],
                    },
                    "meta": {},
                },
                [{"date": "2026-07-19T00:00:00.000Z", "weekIncidence": 0.07}],
            ),
            (
                "testing_history",
                "testing_history",
                {
                    "data": {"history": [{"calendarWeek": "10/2020", "performedTests": 69493}]},
                    "meta": {},
                },
                [{"calendarWeek": "10/2020", "performedTests": 69493}],
            ),
        ]
    )
    def test_nested_history_rows_are_unwrapped(
        self, _name: str, endpoint: str, body: dict, expected: list[dict]
    ) -> None:
        assert _run(endpoint, [_ok(body)]).rows == expected

    @parameterized.expand(
        [
            ("missing_data", "states", {"meta": {}}),
            ("wrong_data_type", "germany_history_cases", {"data": {"unexpected": "shape"}, "meta": {}}),
            ("missing_history", "testing_history", {"data": {}, "meta": {}}),
            ("missing_state_history", "states_history_cases", {"data": {"BY": {"id": 9}}, "meta": {}}),
            ("missing_vaccinations_data", "vaccinations", {"meta": {}}),
            ("age_groups_data_is_list", "states_age_groups", {"data": [], "meta": {}}),
        ]
    )
    def test_malformed_data_yields_no_rows_instead_of_crashing(self, _name: str, endpoint: str, body: dict) -> None:
        assert _run(endpoint, [_ok(body)]).rows == []

    @parameterized.expand(
        [
            ("germany", None, None),
            ("germany_age_groups", ["age_group"], None),
            ("germany_history_cases", ["date"], "date"),
            ("germany_history_hospitalization", ["date"], "date"),
            ("states", ["abbreviation"], None),
            ("states_history_cases", ["abbreviation", "date"], "date"),
            ("districts", ["ags"], None),
            ("testing_history", ["calendarWeek"], None),
        ]
    )
    def test_rki_covid_source_maps_primary_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str] | None, partition_key: str | None
    ) -> None:
        response = _run(endpoint, always(_ok({"data": {}, "meta": {}}))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("reachable", 200, {"cases": 1}, True),
            ("error_envelope", 200, {"error": {"message": "boom"}}, False),
            ("server_error", 500, {}, False),
        ]
    )
    def test_validate_connection(self, _name: str, status: int, body: dict, expected: bool) -> None:
        with scripted_network(always(_ok(body, status))):
            assert validate_connection() is expected

    def test_validate_connection_false_on_network_error(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert validate_connection() is False
