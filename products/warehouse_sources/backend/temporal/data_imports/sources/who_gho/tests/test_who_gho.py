import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho import (
    MAX_INDICATOR_CODES,
    WhoGhoResumeConfig,
    check_indicator_codes,
    parse_indicator_codes,
    validate_credentials,
    who_gho_source,
)

RESOURCE_SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
WHO_GHO_SESSION_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho.make_tracked_session"
)


def _http_response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    response.url = "https://ghoapi.azureedge.net/api/WHOSIS_000001"
    return response


class TestParseIndicatorCodes:
    @parameterized.expand(
        [
            ("WHOSIS_000001", ["WHOSIS_000001"]),
            ("WHOSIS_000001\nWHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("WHOSIS_000001, WHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("WHOSIS_000001;WHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("  WHOSIS_000001  \n\n  WHOSIS_000001 ", ["WHOSIS_000001"]),
            ("", []),
            (None, []),
        ]
    )
    def test_parses_and_deduplicates(self, raw: Optional[str], expected: list[str]) -> None:
        assert parse_indicator_codes(raw) == expected


class TestCheckIndicatorCodes:
    def test_accepts_a_list_at_the_cap(self) -> None:
        assert check_indicator_codes([f"CODE.{index}" for index in range(MAX_INDICATOR_CODES)]) is None

    def test_rejects_an_empty_list(self) -> None:
        error = check_indicator_codes([])

        assert error is not None and "WHOSIS_000001" in error

    def test_rejects_a_list_over_the_cap(self) -> None:
        codes = [f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)]

        error = check_indicator_codes(codes)

        assert error is not None
        assert str(MAX_INDICATOR_CODES) in error
        assert str(len(codes)) in error


class TestWhoGhoSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        indicator_codes: Optional[list[str]] = None,
        should_use_incremental_field: bool = False,
        since: Optional[str] = None,
        dimension_catalog_responses: Optional[list[Response]] = None,
    ) -> tuple[list[dict[str, Any]], list[str], list[list[dict[str, Any]]]]:
        sent_params: list[dict[str, Any]] = []
        sent_urls: list[str] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            sent_urls.append(request.url)
            return next(response_iter)

        with patch(RESOURCE_SESSION_PATH) as MockResourceSession:
            resource_session = MockResourceSession.return_value
            resource_session.headers = {}
            resource_session.prepare_request.side_effect = lambda request: request
            resource_session.send.side_effect = fake_send

            with patch(WHO_GHO_SESSION_PATH) as MockOwnSession:
                if dimension_catalog_responses is not None:
                    MockOwnSession.return_value.get.side_effect = dimension_catalog_responses

                pages = list(
                    who_gho_source(
                        endpoint=endpoint,
                        indicator_codes=indicator_codes or [],
                        team_id=123,
                        job_id="job-id",
                        resumable_source_manager=manager,
                        should_use_incremental_field=should_use_incremental_field,
                        since=since,
                    )
                )

        return sent_params, sent_urls, pages

    def test_catalog_endpoint_paginates_using_skip_and_checkpoints_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        full_page = [{"IndicatorCode": f"CODE{index}"} for index in range(1000)]
        sent_params, sent_urls, pages = self._drive(
            "indicators",
            manager,
            [
                _http_response({"value": full_page}),
                _http_response({"value": []}),
            ],
        )

        # A full page (== $top) means there may be more; a short page below the $top cap is what
        # actually signals the end.
        assert [params["$skip"] for params in sent_params] == [0, 1000]
        assert [params["$top"] for params in sent_params] == [1000, 1000]
        assert sent_urls[0] == "https://ghoapi.azureedge.net/api/Indicator"
        # The empty final page still drives pagination/checkpointing, but the resource wrapper
        # only yields non-empty pages downstream.
        assert pages == [full_page]

        assert [call.args[0] for call in manager.save_state.call_args_list] == [WhoGhoResumeConfig(offset=1000)]
        manager.clear_state.assert_called_once()

    def test_catalog_endpoint_stops_on_a_short_page_without_an_extra_request(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, _, pages = self._drive(
            "dimensions",
            manager,
            [_http_response({"value": [{"Code": "COUNTRY"}]})],
        )

        assert len(sent_params) == 1
        assert pages == [[{"Code": "COUNTRY"}]]
        manager.save_state.assert_not_called()

    def test_catalog_endpoint_resumes_from_the_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WhoGhoResumeConfig(offset=2000)

        sent_params, _, _ = self._drive("indicators", manager, [_http_response({"value": []})])

        assert sent_params[0]["$skip"] == 2000

    def test_indicator_data_walks_every_configured_code(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, sent_urls, pages = self._drive(
            "indicator_data",
            manager,
            [
                _http_response({"value": [{"IndicatorCode": "WHOSIS_000001", "Id": 1}]}),
                _http_response({"value": [{"IndicatorCode": "WHOSIS_000002", "Id": 2}]}),
            ],
            indicator_codes=["WHOSIS_000001", "WHOSIS_000002"],
        )

        assert sent_urls == [
            "https://ghoapi.azureedge.net/api/WHOSIS_000001",
            "https://ghoapi.azureedge.net/api/WHOSIS_000002",
        ]
        assert [row["IndicatorCode"] for page in pages for row in page] == ["WHOSIS_000001", "WHOSIS_000002"]

    def test_indicator_data_applies_the_date_filter_only_on_an_incremental_sync(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, _, _ = self._drive(
            "indicator_data",
            manager,
            [_http_response({"value": []})],
            indicator_codes=["WHOSIS_000001"],
            should_use_incremental_field=True,
            since="2024-08-02",
        )

        assert sent_params[0]["$filter"] == "date(Date) gt 2024-08-02"

    def test_indicator_data_omits_the_filter_on_a_full_sync(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent_params, _, _ = self._drive(
            "indicator_data",
            manager,
            [_http_response({"value": []})],
            indicator_codes=["WHOSIS_000001"],
            should_use_incremental_field=False,
            since="2024-08-02",
        )

        assert "$filter" not in sent_params[0]

    def test_indicator_data_checkpoints_the_next_code_when_one_finishes(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive(
            "indicator_data",
            manager,
            [
                _http_response({"value": [{"IndicatorCode": "A", "Id": index} for index in range(1000)]}),
                _http_response({"value": [{"IndicatorCode": "A", "Id": 1001}]}),
                _http_response({"value": [{"IndicatorCode": "B", "Id": 1}]}),
            ],
            indicator_codes=["A", "B"],
        )

        # A full 1000-row page means there may be more, so the mid-code checkpoint carries the
        # next offset; finishing a code moves to the next one so a restart doesn't re-walk it.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            WhoGhoResumeConfig(offset=1000, item_index=0),
            WhoGhoResumeConfig(offset=0, item_index=1),
            WhoGhoResumeConfig(offset=0, item_index=2),
        ]

    def test_indicator_data_resume_skips_completed_codes(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WhoGhoResumeConfig(offset=3000, item_index=1)

        sent_params, sent_urls, _ = self._drive(
            "indicator_data",
            manager,
            [_http_response({"value": [{"IndicatorCode": "B", "Id": 1}]})],
            indicator_codes=["A", "B"],
        )

        assert sent_urls == ["https://ghoapi.azureedge.net/api/B"]
        assert sent_params[0]["$skip"] == 3000

    @parameterized.expand(
        [
            ([],),
            ([f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)],),
        ]
    )
    def test_indicator_data_refuses_an_out_of_bounds_code_list_before_requesting_anything(
        self, indicator_codes: list[str]
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with pytest.raises(ValueError, match="WHO GHO source misconfigured"):
            self._drive("indicator_data", manager, [], indicator_codes=indicator_codes)

        manager.load_state.assert_not_called()

    def test_dimension_values_fans_out_over_every_discovered_dimension_code(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, sent_urls, pages = self._drive(
            "dimension_values",
            manager,
            [
                _http_response({"value": [{"Code": "AFG", "Dimension": "COUNTRY"}]}),
                _http_response({"value": [{"Code": "SEX_MLE", "Dimension": "SEX"}]}),
            ],
            dimension_catalog_responses=[_http_response({"value": [{"Code": "COUNTRY"}, {"Code": "SEX"}]})],
        )

        assert sent_urls == [
            "https://ghoapi.azureedge.net/api/DIMENSION/COUNTRY/DimensionValues",
            "https://ghoapi.azureedge.net/api/DIMENSION/SEX/DimensionValues",
        ]
        assert [row["Code"] for page in pages for row in page] == ["AFG", "SEX_MLE"]

    def test_dimension_values_paginates_the_dimension_catalog_discovery_call(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        catalog_page_one = _http_response({"value": [{"Code": f"DIM{index}"} for index in range(1000)]})
        catalog_page_two = _http_response({"value": [{"Code": "LASTDIM"}]})

        _, sent_urls, _ = self._drive(
            "dimension_values",
            manager,
            [_http_response({"value": []}) for _ in range(1001)],
            dimension_catalog_responses=[catalog_page_one, catalog_page_two],
        )

        # One DimensionValues request per discovered code, including the one from the second
        # discovery page, confirms discovery did not stop after the first (full) page.
        assert sent_urls[-1] == "https://ghoapi.azureedge.net/api/DIMENSION/LASTDIM/DimensionValues"


class TestValidateCredentials:
    def _validate(self, codes: list[str], responses: list[Response]) -> tuple[bool, Optional[str]]:
        with patch(WHO_GHO_SESSION_PATH) as MockSession:
            MockSession.return_value.get.side_effect = responses
            return validate_credentials(codes)

    def test_rejects_an_empty_code_list(self) -> None:
        ok, error = validate_credentials([])

        assert ok is False
        assert error is not None and "WHOSIS_000001" in error

    def test_rejects_a_code_list_over_the_cap_without_probing(self) -> None:
        ok, error = validate_credentials([f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)])

        assert ok is False
        assert error is not None and str(MAX_INDICATOR_CODES) in error

    def test_accepts_known_codes(self) -> None:
        ok, error = self._validate(["WHOSIS_000001"], [_http_response({"value": [{"IndicatorCode": "WHOSIS_000001"}]})])

        assert (ok, error) == (True, None)

    def test_names_the_codes_that_do_not_exist(self) -> None:
        ok, error = self._validate(
            ["WHOSIS_000001", "NOT_A_REAL_CODE"],
            [
                _http_response({"value": [{"IndicatorCode": "WHOSIS_000001"}]}),
                _http_response({}, status_code=404),
            ],
        )

        assert ok is False
        assert error == "These indicator codes were not found: NOT_A_REAL_CODE."

    @parameterized.expand([(500,), (503,), (429,)])
    def test_reports_an_unreachable_api(self, status_code: int) -> None:
        ok, error = self._validate(["WHOSIS_000001"], [_http_response({}, status_code=status_code)])

        assert ok is False
        assert error == "Could not reach the WHO Global Health Observatory API. Please try again."
