from datetime import UTC, datetime
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.sources.deputy._config import DeputySourceConfig
from products.warehouse_sources.sources.deputy.deputy import (
    DeputyResumeConfig,
    InvalidDeputyInstallError,
    format_modified_since,
    normalize_install_host,
)
from products.warehouse_sources.sources.deputy.settings import PAGE_SIZE
from products.warehouse_sources.sources.deputy.source import DeputySource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

INSTALL_URL = "https://acme.au.deputy.com"


def _driver() -> SourceDriver:
    return SourceDriver(DeputySource(), DeputySourceConfig(install_url=INSTALL_URL, access_token="test-token"))


def _rows(field: str, values: list[Any]) -> list[dict[str, Any]]:
    return [{"Id": index, field: value} for index, value in enumerate(values)]


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


def _bodies(result: Any) -> list[dict[str, Any]]:
    return [request.json() for request in result.requests]


class TestNormalizeInstallHost:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("https://acme.au.deputy.com", "acme.au.deputy.com"),
            ("https://acme.au.deputy.com/#/timesheets", "acme.au.deputy.com"),
            ("acme.na.deputy.com/", "acme.na.deputy.com"),
            ("  HTTPS://Acme.UK.Deputy.com  ", "acme.uk.deputy.com"),
            ("http://acme.au.deputy.com", "acme.au.deputy.com"),
            ("usdemo.ent-na.deputy.com", "usdemo.ent-na.deputy.com"),
            ("acme.au", "acme.au.deputy.com"),
            ("acme", "acme.deputy.com"),
        ],
    )
    def test_accepts_deputy_install_hosts(self, value: str, expected: str) -> None:
        assert normalize_install_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            # Each of these would send the token to a host outside deputy.com, or to an unexpected port.
            "https://acme.deputy.com.evil.com",
            "https://acme.deputy.com@evil.com",
            "https://user@acme.au.deputy.com",
            "https://acme.au.deputy.com:8443",
            "ftp://acme.au.deputy.com",
            "https://a.b.c.deputy.com",
            "https://-acme.au.deputy.com",
            "https://acme_1.au.deputy.com",
        ],
    )
    def test_rejects_other_hosts(self, value: str) -> None:
        with pytest.raises(InvalidDeputyInstallError):
            normalize_install_host(value)


class TestFormatModifiedSince:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # The value starts 14 hours early, so a filter that Deputy reads in the install's time zone
            # still covers every row.
            (datetime(2024, 3, 2, 12, 0, 0, tzinfo=UTC), "2024-03-01T22:00:00+00:00"),
            (datetime(2024, 3, 2, 12, 0, 0), "2024-03-01T22:00:00+00:00"),
            (datetime.fromisoformat("2024-03-02T22:00:00+10:00"), "2024-03-01T22:00:00+00:00"),
            ("2024-03-02T12:00:00+10:00", "2024-03-02T12:00:00+10:00"),
        ],
    )
    def test_formats_watermark(self, value: Any, expected: str) -> None:
        assert format_modified_since(value) == expected


class TestPagination:
    def test_full_refresh_pages_by_id_until_a_short_page(self) -> None:
        first = [{"Id": index} for index in range(1, PAGE_SIZE + 1)]
        second = [{"Id": index} for index in range(PAGE_SIZE + 1, 2 * PAGE_SIZE + 1)]
        last = [{"Id": 2 * PAGE_SIZE + 1}]

        result = _driver().run("timesheets", [_page(first), _page(second), _page(last)])

        assert result.raised is None
        assert len(result.rows) == 2 * PAGE_SIZE + 1
        assert result.paths == ["/api/v1/resource/Timesheet/QUERY"] * 3
        assert {request.method for request in result.requests} == {"POST"}
        assert result.requests[0].headers["authorization"] == "Bearer test-token"
        assert _bodies(result) == [
            {"sort": {"Id": "asc"}, "start": 0, "max": PAGE_SIZE},
            {
                "sort": {"Id": "asc"},
                "start": 1,
                "max": PAGE_SIZE,
                "search": {"s1": {"field": "Id", "type": "ge", "data": PAGE_SIZE}},
            },
            {
                "sort": {"Id": "asc"},
                "start": 1,
                "max": PAGE_SIZE,
                "search": {"s1": {"field": "Id", "type": "ge", "data": 2 * PAGE_SIZE}},
            },
        ]
        assert result.saved_states == [
            DeputyResumeConfig(field="Id", value=PAGE_SIZE, skip=1),
            DeputyResumeConfig(field="Id", value=2 * PAGE_SIZE, skip=1),
        ]
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_incremental_pages_by_modified_and_skips_only_rows_already_read(self) -> None:
        t1, t2 = "2024-03-02T10:00:00+10:00", "2024-03-02T11:00:00+10:00"
        # Page one ends with three rows at t2. Page two holds only t2 rows, so the skip grows instead
        # of the lower bound moving.
        first = _rows("Modified", [t1] * (PAGE_SIZE - 3) + [t2] * 3)
        second = _rows("Modified", [t2] * PAGE_SIZE)
        last = _rows("Modified", ["2024-03-02T12:00:00+10:00"])

        result = _driver().run(
            "employees",
            [_page(first), _page(second), _page(last)],
            incremental_field="Modified",
            db_incremental_field_last_value=datetime(2024, 3, 2, 0, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/resource/Employee/QUERY"] * 3
        assert [(body["search"]["s1"]["data"], body["start"]) for body in _bodies(result)] == [
            ("2024-03-01T10:00:00+00:00", 0),
            (t2, 3),
            (t2, 3 + PAGE_SIZE),
        ]
        assert {body["search"]["s1"]["type"] for body in _bodies(result)} == {"ge"}
        assert {tuple(body["sort"].items()) for body in _bodies(result)} == {(("Modified", "asc"),)}
        assert result.response is not None
        assert result.response.sort_mode == "asc"

    def test_first_incremental_sync_sends_no_filter_but_sorts_by_modified(self) -> None:
        result = _driver().run(
            "employees",
            [_page(_rows("Modified", ["2024-03-02T10:00:00+10:00"]))],
            incremental_field="Modified",
        )

        assert result.raised is None
        assert _bodies(result) == [{"sort": {"Modified": "asc"}, "start": 0, "max": PAGE_SIZE}]

    def test_full_page_whose_last_row_has_no_cursor_value_fails_instead_of_looping(self) -> None:
        page = _rows("Modified", ["2024-03-02T10:00:00+10:00"] * (PAGE_SIZE - 1) + [None])

        result = _driver().run("employees", [_page(page)], incremental_field="Modified")

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 1

    def test_object_body_fails_the_run(self) -> None:
        result = _driver().run("employees", [ScriptedResponse(json={"error": {"code": 500, "message": "boom"}})])

        assert isinstance(result.raised, ValueError)
        assert result.rows == []


class TestResume:
    @pytest.mark.parametrize(
        ("resume_state", "incremental", "expected_body"),
        [
            (
                DeputyResumeConfig(field="Id", value=1500, skip=1),
                False,
                {
                    "sort": {"Id": "asc"},
                    "start": 1,
                    "max": PAGE_SIZE,
                    "search": {"s1": {"field": "Id", "type": "ge", "data": 1500}},
                },
            ),
            (
                DeputyResumeConfig(field="Modified", value="2024-03-02T11:00:00+10:00", skip=4),
                True,
                {
                    "sort": {"Modified": "asc"},
                    "start": 4,
                    "max": PAGE_SIZE,
                    "search": {"s1": {"field": "Modified", "type": "ge", "data": "2024-03-02T11:00:00+10:00"}},
                },
            ),
            # A cursor saved by a run on the other sync mode points into another order, so it is ignored.
            (
                DeputyResumeConfig(field="Modified", value="2024-03-02T11:00:00+10:00", skip=4),
                False,
                {"sort": {"Id": "asc"}, "start": 0, "max": PAGE_SIZE},
            ),
        ],
    )
    def test_resume_starts_from_saved_state(
        self, resume_state: DeputyResumeConfig, incremental: bool, expected_body: dict[str, Any]
    ) -> None:
        result = _driver().run(
            "rosters",
            [_page([{"Id": 1, "Modified": "2024-03-02T12:00:00+10:00"}])],
            resume_state=resume_state,
            incremental_field="Modified",
            should_use_incremental_field=incremental,
        )

        assert result.raised is None
        assert _bodies(result) == [expected_body]


class TestErrors:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_errors_surface_with_status_text(self, status: int) -> None:
        result = _driver().run("employees", always(ScriptedResponse(status=status, json={"error": "denied"})))

        assert isinstance(result.raised, HTTPError)
        assert str(status) in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, (True, None)),
            (
                401,
                (
                    False,
                    "Deputy rejected the permanent token. Create a new token in your Deputy install, then try again.",
                ),
            ),
            (
                500,
                (
                    False,
                    "Deputy returned an unexpected status (500). Check the Deputy URL and token, then try again.",
                ),
            ),
        ],
    )
    def test_probes_the_install(self, status: int, expected: tuple[bool, str | None]) -> None:
        config = DeputySourceConfig(install_url="acme.au.deputy.com", access_token="test-token")
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            assert DeputySource().validate_credentials(config, team_id=1) == expected

        assert {request.url for request in network.requests_log} == {"https://acme.au.deputy.com/api/v1/me"}
        assert network.requests_log[0].headers["authorization"] == "Bearer test-token"

    def test_rejects_a_host_outside_deputy_without_a_request(self) -> None:
        config = DeputySourceConfig(install_url="https://evil.example.com:8443", access_token="test-token")
        with scripted_network([]) as network:
            is_valid, message = DeputySource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and message.startswith("Invalid Deputy URL")
        assert network.requests_log == []
