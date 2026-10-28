from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.worldbank import (
    WorldBankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.source import WorldBankSource
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.world_bank import (
    DATA_SELECTOR,
    MAX_INDICATOR_CODES,
    WorldBankPaginator,
    WorldBankResumeConfig,
    check_indicator_codes,
    validate_credentials,
)


def _payload(rows: Any, pages: Any = 1, page: Any = 1) -> list[Any]:
    return [{"page": page, "pages": pages, "per_page": "1000", "total": 1}, rows]


def _meta_response(pages: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = _payload([{"id": "ABW"}], pages=pages)
    return response


class TestCheckIndicatorCodes:
    def test_rejects_an_empty_list(self) -> None:
        error = check_indicator_codes([])

        assert error is not None and "SP.POP.TOTL" in error

    def test_rejects_a_list_over_the_cap(self) -> None:
        # Each code costs its own full-history walk on every refresh, so an unbounded list would
        # let one source consume worker, network, and storage capacity indefinitely.
        codes = [f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)]

        error = check_indicator_codes(codes)

        assert error is not None
        assert str(MAX_INDICATOR_CODES) in error
        assert str(len(codes)) in error


class TestWorldBankPaginator:
    @pytest.mark.parametrize(
        ("pages", "expected_has_next"),
        [
            # Catalog endpoints report the page count as a number, others as a string; both have
            # to stop pagination at the same place.
            (3, True),
            ("3", True),
            (1, False),
            ("1", False),
            # An unreadable page count falls back to walking until an empty page.
            (None, True),
            ("not-a-number", True),
        ],
    )
    def test_stops_at_the_reported_page_count(self, pages: Any, expected_has_next: bool) -> None:
        paginator = WorldBankPaginator()
        paginator.update_state(_meta_response(pages), data=[{"id": "ABW"}])

        assert paginator.page == 2
        assert paginator.has_next_page is expected_has_next

    @pytest.mark.parametrize("body", [[], [{"page": 1}], "not-json"])
    def test_falls_back_to_walking_when_the_page_count_is_unreadable(self, body: Any) -> None:
        # A body with no metadata object, or one the JSON decoder rejects outright, must not
        # abort pagination — it just costs one extra request to find the end.
        response = MagicMock()
        if body == "not-json":
            response.json.side_effect = ValueError("no JSON object could be decoded")
        else:
            response.json.return_value = body

        paginator = WorldBankPaginator()
        paginator.update_state(response, data=[{"id": "ABW"}])

        assert paginator.has_next_page is True

    def test_str_reports_the_current_page(self) -> None:
        paginator = WorldBankPaginator(page=7)

        assert str(paginator) == "WorldBankPaginator(page=7)"

    def test_stops_on_empty_page(self) -> None:
        # Requesting a page past the end answers 200 with an empty row list rather than an error.
        paginator = WorldBankPaginator()
        paginator.update_state(_meta_response(99), data=[])

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None


class TestRequiredDataSelector:
    def test_error_envelope_raises_a_message_the_source_can_classify(self) -> None:
        # An unknown indicator code comes back as HTTP 200 with an error envelope. The raised
        # message is what `WorldBankSource.get_non_retryable_errors` matches on, so the two must
        # stay in step.
        with pytest.raises(ValueError) as excinfo:
            RESTClient()._extract_response(
                [{"message": [{"id": "120", "key": "Invalid value"}]}], DATA_SELECTOR, required=True
            )

        assert "Required data_selector '[1]' matched nothing in the response" in str(excinfo.value)


class TestWorldBankSourceTransport:
    @staticmethod
    def _driver(indicator_codes: str = "") -> SourceDriver:
        return SourceDriver(WorldBankSource(), WorldBankSourceConfig(indicator_codes=indicator_codes))

    def test_indicator_data_checkpoints_the_next_code_when_one_finishes(self) -> None:
        result = self._driver("A\nB").run(
            "indicator_data",
            [
                ScriptedResponse(
                    json=_payload([{"indicator": {"id": "A"}, "country": {"id": "US"}, "date": "2024"}], pages=2)
                ),
                ScriptedResponse(
                    json=_payload(
                        [{"indicator": {"id": "A"}, "country": {"id": "US"}, "date": "2023"}], pages=2, page=2
                    )
                ),
                ScriptedResponse(json=_payload([{"indicator": {"id": "B"}, "country": {"id": "US"}, "date": "2024"}])),
            ],
        )

        # Mid-code checkpoints carry the next page; finishing a code moves to the next one so a
        # restart doesn't re-walk codes that already completed.
        assert result.saved_states == [
            WorldBankResumeConfig(page=2, indicator_index=0),
            WorldBankResumeConfig(page=1, indicator_index=1),
            WorldBankResumeConfig(page=1, indicator_index=2),
        ]

    def test_indicator_data_resume_skips_completed_codes(self) -> None:
        result = self._driver("A\nB").run(
            "indicator_data",
            [
                ScriptedResponse(
                    json=_payload([{"indicator": {"id": "B"}, "country": {"id": "US"}, "date": "2024"}], pages=3)
                )
            ],
            resume_state=WorldBankResumeConfig(page=3, indicator_index=1),
        )

        assert [request.origin + request.path for request in result.requests] == [
            "https://api.worldbank.org/v2/country/all/indicator/B"
        ]
        assert result.params("page") == ["3"]

    @pytest.mark.parametrize(
        "indicator_codes",
        [[], [f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)]],
    )
    def test_indicator_data_refuses_an_out_of_bounds_code_list_before_requesting_anything(
        self, indicator_codes: list[str]
    ) -> None:
        # Validation runs at source-create, but a config saved before the cap existed (or through
        # anything but the form) would otherwise fan out unbounded on every refresh.
        result = self._driver("\n".join(indicator_codes)).run("indicator_data", [])

        assert isinstance(result.raised, ValueError)
        assert "World Bank source misconfigured" in str(result.raised)
        assert result.requests == []


class TestValidateCredentials:
    @staticmethod
    def _validate(codes: list[str], responses: list[ScriptedResponse]) -> tuple[bool, str | None]:
        with scripted_network(responses):
            return validate_credentials(codes, "v2")

    def test_rejects_an_empty_code_list(self) -> None:
        ok, error = validate_credentials([], "v2")

        assert ok is False
        assert error is not None and "SP.POP.TOTL" in error

    def test_rejects_a_code_list_over_the_cap_without_probing(self) -> None:
        # The cap has to be enforced at create time, not just at sync time, so an oversized list
        # can never be saved in the first place.
        ok, error = validate_credentials([f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)], "v2")

        assert ok is False
        assert error is not None and str(MAX_INDICATOR_CODES) in error

    def test_accepts_known_codes(self) -> None:
        ok, error = self._validate(
            ["SP.POP.TOTL"], [ScriptedResponse(json=_payload([{"id": "SP.POP.TOTL", "name": "Population, total"}]))]
        )

        assert (ok, error) == (True, None)

    def test_names_the_codes_that_do_not_exist(self) -> None:
        # An unknown code answers HTTP 200 with a single-element error envelope, so a status check
        # alone would let it through and the sync would fail later instead.
        ok, error = self._validate(
            ["SP.POP.TOTL", "NOT.A.CODE"],
            [
                ScriptedResponse(json=_payload([{"id": "SP.POP.TOTL"}])),
                ScriptedResponse(json=[{"message": [{"id": "120", "key": "Invalid value"}]}]),
            ],
        )

        assert ok is False
        assert error == "These indicator codes were not found: NOT.A.CODE."

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_reports_an_unreachable_api(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=[]))):
            ok, error = validate_credentials(["SP.POP.TOTL"], "v2")

        assert ok is False
        assert error == "Could not reach the World Bank Indicators API. Please try again."

    def test_reports_a_non_json_response(self) -> None:
        # The World Bank fronts the API with a WAF that answers HTML on a block.
        ok, error = self._validate(["SP.POP.TOTL"], [ScriptedResponse(body=b"<!DOCTYPE html><html></html>")])

        assert ok is False
        assert error == "The World Bank Indicators API returned an unexpected response. Please try again."
