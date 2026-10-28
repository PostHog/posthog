from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rentcast import (
    RentCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import (
    INVALID_ZIP_CODES_ERROR,
    MISSING_ZIP_CODES_ERROR,
    PAGE_SIZE,
    RentCastResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import (
    ENDPOINTS,
    RENTCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.source import RentCastSource


def _driver(zip_codes: str | None = "10001") -> SourceDriver:
    return SourceDriver(RentCastSource(), RentCastSourceConfig(api_key="rc-key", zip_codes=zip_codes))


def _page(body: Any) -> ScriptedResponse:
    # RentCast list endpoints return a bare JSON array of records.
    return ScriptedResponse(json=body)


def _full_page(start_id: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


def _market(zip_code: str) -> dict[str, Any]:
    return {"id": zip_code, "zipCode": zip_code, "rentalData": {"averageRent": 1850, "history": {}}}


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run("properties", [_page(_full_page(0)), _page([{"id": 999}])])

        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": 999}
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.requests[0].param("limit") == str(PAGE_SIZE)
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [RentCastResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("properties", [_page([{"id": 5}])], resume_state=RentCastResumeConfig(offset=PAGE_SIZE))

        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        assert result.params("offset") == [str(PAGE_SIZE)]
        assert result.rows == [{"id": 5}]

    @parameterized.expand([("bare_string", "nope"), ("dict_without_list", {"error": "nope"})])
    def test_non_list_body_is_retryable(self, _name: str, bad_body: Any) -> None:
        # A 200 body that isn't a list means an unexpected shape — retry, don't sync garbage.
        result = _driver().run("properties", always(_page(bad_body)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "Unexpected 200 response body shape" in str(result.raised)


class TestMarkets:
    def test_requests_each_zip_code_and_skips_zip_codes_without_data(self) -> None:
        result = _driver(zip_codes=" 10001, 20002\n10001 30003 ").run(
            "markets",
            [
                _page(_market("10001")),
                ScriptedResponse(status=404, json={"status": 404, "error": "resource/not-found"}),
                _page(_market("30003")),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/markets"] * 3
        assert result.params("zipCode") == ["10001", "20002", "30003"]
        assert [row["id"] for row in result.rows] == ["10001", "30003"]
        assert result.rows[0]["rentalData"] == {"averageRent": 1850, "history": {}}
        assert result.saved_states == [
            RentCastResumeConfig(next_zip_code="20002"),
            RentCastResumeConfig(next_zip_code="30003"),
        ]
        assert result.committed_states[-1] == RentCastResumeConfig(next_zip_code="30003")

    def test_resumes_from_saved_zip_code_position(self) -> None:
        result = _driver(zip_codes="10001,20002,30003").run(
            "markets", [_page(_market("30003"))], resume_state=RentCastResumeConfig(next_zip_code="30003")
        )

        assert result.params("zipCode") == ["30003"]
        assert [row["id"] for row in result.rows] == ["30003"]

    def test_resume_follows_the_zip_code_when_the_list_was_edited(self) -> None:
        result = _driver(zip_codes="40004,30003").run(
            "markets", [_page(_market("30003"))], resume_state=RentCastResumeConfig(next_zip_code="30003")
        )

        assert result.params("zipCode") == ["30003"]

    def test_resume_restarts_when_the_saved_zip_code_was_removed(self) -> None:
        result = _driver(zip_codes="10001,20002").run(
            "markets",
            [_page(_market("10001")), _page(_market("20002"))],
            resume_state=RentCastResumeConfig(next_zip_code="30003"),
        )

        assert result.params("zipCode") == ["10001", "20002"]

    @parameterized.expand(
        [
            ("not_set", None, MISSING_ZIP_CODES_ERROR),
            ("empty", "", MISSING_ZIP_CODES_ERROR),
            ("only_separators", " , ,", MISSING_ZIP_CODES_ERROR),
            ("too_short", "10001, 2002", INVALID_ZIP_CODES_ERROR),
            ("zip_plus_four", "10001-1234", INVALID_ZIP_CODES_ERROR),
            ("not_digits", "abcde", INVALID_ZIP_CODES_ERROR),
        ]
    )
    def test_bad_zip_codes_fail_before_any_request_with_a_non_retryable_error(
        self, _name: str, zip_codes: str | None, expected_error: str
    ) -> None:
        result = _driver(zip_codes=zip_codes).run("markets", [])

        assert isinstance(result.raised, ValueError)
        assert expected_error in str(result.raised)
        assert result.requests == []
        assert any(key in str(result.raised) for key in RentCastSource().get_non_retryable_errors())

    def test_bad_zip_codes_do_not_block_other_tables(self) -> None:
        result = _driver(zip_codes="abcde").run("properties", [_page([{"id": 1}])])

        assert result.raised is None
        assert result.rows == [{"id": 1}]

    @parameterized.expand([(401,), (403,)])
    def test_auth_failures_map_to_non_retryable_errors(self, status: int) -> None:
        result = _driver().run("markets", always(ScriptedResponse(status=status, json={"status": status})))

        assert result.raised is not None
        assert any(key in str(result.raised) for key in RentCastSource().get_non_retryable_errors())


class TestRentCastSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every record, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RENTCAST_ENDPOINTS.values())
        assert set(RENTCAST_ENDPOINTS) == set(ENDPOINTS)
