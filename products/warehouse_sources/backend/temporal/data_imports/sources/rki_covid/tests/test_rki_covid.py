from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.rki_covid import (
    RKICovidAPIError,
    _fetch,
    build_url,
    get_rows,
    rki_covid_source,
    validate_connection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.settings import RKI_COVID_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.rki_covid"


def _response(*, body: Any = None, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body if body is not None else {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _session_returning(response: MagicMock) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    return session


def _collect_rows(batches: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in batches:
        rows.extend(batch)
    return rows


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
        session = _session_returning(_response(body={"error": {"message": "wrong route"}}))
        with pytest.raises(RKICovidAPIError, match="error_response"):
            _fetch(session, "https://api.corona-zahlen.org/germany")

    def test_fetch_raises_on_non_dict_body(self) -> None:
        session = _session_returning(_response(body=["unexpected"]))
        with pytest.raises(RKICovidAPIError, match="unexpected_response"):
            _fetch(session, "https://api.corona-zahlen.org/germany")

    def test_fetch_raises_on_http_error(self) -> None:
        session = _session_returning(_response(status=404))
        with pytest.raises(requests.HTTPError):
            _fetch(session, "https://api.corona-zahlen.org/germany")

    def test_germany_snapshot_yields_single_row(self) -> None:
        body = {"cases": 100, "deaths": 5, "meta": {"lastUpdate": "2026-07-21T05:35:57.000Z"}}
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            rows = _collect_rows(get_rows("germany", None, MagicMock()))
        assert rows == [body]

    def test_age_groups_inject_dict_key_as_age_group_column(self) -> None:
        # The age band only exists as the dict key; dropping it would leave rows with no identity.
        body = {
            "data": {
                "A00-A04": {"casesMale": 1, "casesFemale": 2},
                "A80+": {"casesMale": 3, "casesFemale": 4},
            },
            "meta": {},
        }
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            rows = _collect_rows(get_rows("germany_age_groups", None, MagicMock()))
        assert rows == [
            {"age_group": "A00-A04", "casesMale": 1, "casesFemale": 2},
            {"age_group": "A80+", "casesMale": 3, "casesFemale": 4},
        ]

    def test_states_yield_one_row_per_dict_value(self) -> None:
        body = {
            "data": {
                "SH": {"id": 1, "abbreviation": "SH", "name": "Schleswig-Holstein", "cases": 10},
                "HH": {"id": 2, "abbreviation": "HH", "name": "Hamburg", "cases": 20},
            },
            "meta": {},
        }
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            rows = _collect_rows(get_rows("states", None, MagicMock()))
        assert [r["abbreviation"] for r in rows] == ["SH", "HH"]

    def test_history_list_yields_data_rows(self) -> None:
        body = {
            "data": [
                {"cases": 0, "date": "2026-07-18T00:00:00.000Z"},
                {"cases": 7, "date": "2026-07-20T00:00:00.000Z"},
            ],
            "meta": {},
        }
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            rows = _collect_rows(get_rows("germany_history_cases", None, MagicMock()))
        assert rows == body["data"]

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
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            rows = _collect_rows(get_rows(endpoint, None, MagicMock()))
        assert rows == expected

    @parameterized.expand(
        [
            ("missing_data", "states", {"meta": {}}),
            ("wrong_data_type", "germany_history_cases", {"data": {"unexpected": "shape"}, "meta": {}}),
            ("missing_history", "testing_history", {"data": {}, "meta": {}}),
        ]
    )
    def test_malformed_data_yields_no_rows_instead_of_crashing(self, _name: str, endpoint: str, body: dict) -> None:
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(_response(body=body))):
            assert _collect_rows(get_rows(endpoint, None, MagicMock())) == []

    def test_get_rows_requests_days_trimmed_url(self) -> None:
        session = _session_returning(_response(body={"data": [], "meta": {}}))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            _collect_rows(get_rows("germany_history_cases", 90, MagicMock()))
        assert session.get.call_args.args[0] == "https://api.corona-zahlen.org/germany/history/cases/90"

    @parameterized.expand(
        [
            ("germany", None, None),
            ("germany_age_groups", ["age_group"], None),
            ("germany_history_cases", ["date"], "date"),
            ("germany_history_hospitalization", ["date"], "date"),
            ("states", ["abbreviation"], None),
            ("districts", ["ags"], None),
            ("testing_history", ["calendarWeek"], None),
        ]
    )
    def test_rki_covid_source_maps_primary_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str] | None, partition_key: str | None
    ) -> None:
        response = rki_covid_source(endpoint, None, MagicMock())
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
        session = _session_returning(_response(body=body, status=status))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_connection() is expected

    def test_validate_connection_false_on_network_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_connection() is False
