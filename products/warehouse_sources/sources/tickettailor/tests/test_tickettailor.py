from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tickettailor import (
    TicketTailorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.source import TicketTailorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tickettailor.tickettailor import (
    PAGE_SIZE,
    TicketTailorResumeConfig,
    validate_credentials,
)


def _page(items: list[dict[str, Any]] | None, *, next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"links": {"next": next_link, "previous": None}, "data": items or []})


def _run(script: Script, endpoint: str = "orders", resume_state: TicketTailorResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(TicketTailorSource(), TicketTailorSourceConfig(api_key="tt-key"))
    return driver.run(endpoint, script, resume_state=resume_state)


class TestPagination:
    def test_follows_cursor_until_no_next_link(self) -> None:
        first_page = [{"id": f"or_{i}"} for i in range(PAGE_SIZE)]
        result = _run(
            [
                _page(first_page, next_link="https://api.tickettailor.com/v1/orders?starting_after=or_99"),
                _page([{"id": "or_100"}], next_link=None),
            ],
        )

        assert [r["id"] for r in result.rows] == [*(f"or_{i}" for i in range(PAGE_SIZE)), "or_100"]
        # First request carries only limit; the second advances via the last id of page one.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),)}
        assert result.queries[1] == {"limit": (str(PAGE_SIZE),), "starting_after": ("or_99",)}
        # Checkpoint saved once, after the first page (points at the next page); the null next link ends it.
        assert result.saved_states == [TicketTailorResumeConfig(cursor="or_99")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _run([_page([{"id": "or_51"}], next_link=None)], resume_state=TicketTailorResumeConfig(cursor="or_50"))

        assert [r["id"] for r in result.rows] == ["or_51"]
        # The uncursored first page must never be fetched on resume.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),), "starting_after": ("or_50",)}


class TestMalformedBodyIsRetryable:
    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "or_1"}]),
            ("missing_data_key", {"links": {"next": None}}),
        ]
    )
    def test_unexpected_shape_is_retried_then_reraised(self, _name: str, body: Any) -> None:
        # A 200 whose body isn't {"data": [...], ...} is treated as a transient truncation: retried
        # (up to the client's attempt cap) rather than ingested as a stray row.
        result = _run(always(ScriptedResponse(json=body)))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestValidateCredentials:
    def test_connection_error_maps_to_could_not_validate(self) -> None:
        # validate_via_probe swallows transport errors; the probe reports "not validated".
        with scripted_network(always(ConnectionResetError("reset"))):
            assert validate_credentials("tt-key") == (False, "Could not validate Ticket Tailor API key")


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run([_page([])], endpoint).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists come back newest-first; declaring asc would corrupt a future incremental watermark.
        assert response.sort_mode == "desc"
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
