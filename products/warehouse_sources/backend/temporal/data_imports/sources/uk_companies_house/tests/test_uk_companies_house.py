import json
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Request, RequestException, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    CHARGES,
    COMPANIES,
    FILING_HISTORY,
    INSOLVENCY,
    ITEMS_PER_PAGE,
    OFFICERS,
    PERSONS_WITH_SIGNIFICANT_CONTROL,
    PSC_STATEMENTS,
    UK_ESTABLISHMENTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.uk_companies_house import (
    CompaniesHouseOffsetPaginator,
    UkCompaniesHouseResumeConfig,
    invalid_company_numbers,
    parse_company_numbers,
    uk_companies_house_source,
    validate_credentials,
)

SESSION_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.uk_companies_house.make_tracked_session"


def _response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://api.company-information.service.gov.uk/company/00006400"
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _drive_session(responses: list[Response]) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    """Patch the tracked session so `RESTClient.paginate` runs against canned responses.

    Returns the patcher and the (url, params) actually sent, captured at send time because the
    paginator mutates one `Request` in place across pages.
    """
    sent: list[tuple[str, dict[str, Any]]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent.append((request.url, dict(request.params or {})))
        return next(response_iter)

    patcher = patch(SESSION_TARGET)
    mock_make_session = patcher.start()
    mock_session = mock_make_session.return_value
    mock_session.headers = {}
    mock_session.prepare_request.side_effect = lambda req: req
    mock_session.send.side_effect = fake_send
    return patcher, sent


def _manager(resume: Optional[UkCompaniesHouseResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _run(endpoint: str, company_numbers: list[str], responses: list[Response], resume=None):
    patcher, sent = _drive_session(responses)
    manager = _manager(resume)
    try:
        pages = list(
            uk_companies_house_source(
                api_key="key",
                endpoint=endpoint,
                company_numbers=company_numbers,
                resumable_source_manager=manager,
                logger=MagicMock(),
            )
        )
    finally:
        patcher.stop()
    return pages, sent, manager


class TestParseCompanyNumbers:
    @parameterized.expand(
        [
            ("newlines", "00006400\nSC123456", ["00006400", "SC123456"]),
            ("commas_and_spaces", "00006400, sc123456 ;OC301365", ["00006400", "SC123456", "OC301365"]),
            ("zero_pads_short_numeric", "6400", ["00006400"]),
            ("keeps_alphanumeric_as_typed", "br000123", ["BR000123"]),
            ("dedupes_preserving_order", "00006400\n6400\nSC123456", ["00006400", "SC123456"]),
            ("blank", "   \n , ", []),
            ("none", None, []),
        ]
    )
    def test_parse(self, _label: str, raw: Optional[str], expected: list[str]) -> None:
        assert parse_company_numbers(raw) == expected

    @parameterized.expand(
        [
            ("valid_numeric", ["00006400"], []),
            ("valid_prefixed", ["SC123456", "OC301365", "NI123456"], []),
            ("too_short", ["ABC123"], ["ABC123"]),
            ("too_long", ["000064000"], ["000064000"]),
            ("punctuation", ["0000-640"], ["0000-640"]),
        ]
    )
    def test_invalid_company_numbers(self, _label: str, numbers: list[str], expected: list[str]) -> None:
        assert invalid_company_numbers(numbers) == expected


class TestCompaniesHouseOffsetPaginator:
    def test_init_request_seeds_offset_params(self) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", start_index=40)
        request = Request(method="GET", url="https://api.company-information.service.gov.uk/company/1/officers")
        paginator.init_request(request)

        assert request.params == {"start_index": 40, "items_per_page": ITEMS_PER_PAGE}

    def test_advances_by_rows_returned_not_requested_page_size(self) -> None:
        # Companies House caps items_per_page per endpoint and silently returns fewer rows;
        # striding by the requested size would skip everything it did not send.
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=100)
        rows = [{"n": i} for i in range(35)]
        paginator.update_state(_response({"total_results": 70, "items": rows}), rows)

        assert paginator.start_index == 35
        assert paginator.has_next_page is True

    @parameterized.expand(
        [
            ("stops_at_total", {"total_results": 2}, [{"n": 1}, {"n": 2}], 2, False),
            ("continues_below_total", {"total_results": 9}, [{"n": 1}, {"n": 2}], 2, True),
            ("stops_on_empty_page", {"total_results": 9}, [], 0, False),
            ("stops_on_short_page_without_total", {}, [{"n": 1}], 1, False),
            ("continues_on_full_page_without_total", {}, [{"n": 1}, {"n": 2}], 2, True),
            ("ignores_non_integer_total", {"total_results": "many"}, [{"n": 1}], 1, False),
        ]
    )
    def test_update_state(
        self,
        _label: str,
        body: dict[str, Any],
        rows: list[dict[str, Any]],
        expected_start_index: int,
        expected_has_next: bool,
    ) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        paginator.update_state(_response(body), rows)

        assert paginator.start_index == expected_start_index
        assert paginator.has_next_page is expected_has_next

    def test_resume_state_round_trip(self) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        paginator.update_state(_response({"total_results": 9}), [{"n": 1}, {"n": 2}])
        state = paginator.get_resume_state()
        assert state == {"start_index": 2}

        resumed = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        resumed.set_resume_state(state or {})
        assert resumed.start_index == 2
        assert resumed.has_next_page is True

    def test_no_resume_state_once_exhausted(self) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        paginator.update_state(_response({"total_results": 1}), [{"n": 1}])

        assert paginator.get_resume_state() is None


class TestUkCompaniesHouseSource:
    @parameterized.expand(
        [
            (
                "profile_is_one_row_untouched",
                COMPANIES,
                {"company_number": "00006400", "company_name": "Acme"},
                [{"company_number": "00006400", "company_name": "Acme"}],
            ),
            (
                "single_object_endpoint_gets_company_number",
                INSOLVENCY,
                {"status": "liquidation", "cases": [{"type": "compulsory-liquidation"}]},
                [
                    {
                        "status": "liquidation",
                        "cases": [{"type": "compulsory-liquidation"}],
                        "company_number": "00006400",
                    }
                ],
            ),
            (
                "officers_get_appointment_id_from_self_link",
                OFFICERS,
                {
                    "total_results": 1,
                    "items": [{"name": "A Person", "links": {"self": "/company/00006400/appointments/xyz"}}],
                },
                [
                    {
                        "name": "A Person",
                        "links": {"self": "/company/00006400/appointments/xyz"},
                        "company_number": "00006400",
                        "appointment_id": "xyz",
                    }
                ],
            ),
            (
                "officers_without_self_link_get_no_id",
                OFFICERS,
                {"total_results": 1, "items": [{"name": "A Person"}]},
                [{"name": "A Person", "company_number": "00006400", "appointment_id": None}],
            ),
            (
                "establishments_keep_their_own_company_number",
                UK_ESTABLISHMENTS,
                {"items": [{"company_number": "BR000123", "company_name": "Branch"}]},
                [
                    {
                        "company_number": "BR000123",
                        "company_name": "Branch",
                        "parent_company_number": "00006400",
                    }
                ],
            ),
        ]
    )
    def test_row_normalization_per_endpoint(
        self, _label: str, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        pages, _sent, _manager_mock = _run(endpoint, ["00006400"], [_response(body)])

        assert pages == [expected]

    def test_fans_out_over_every_company_number(self) -> None:
        pages, sent, manager = _run(
            OFFICERS,
            ["00006400", "SC123456"],
            [
                _response({"total_results": 1, "items": [{"name": "First"}]}),
                _response({"total_results": 1, "items": [{"name": "Second"}]}),
            ],
        )

        assert [url for url, _params in sent] == [
            "https://api.company-information.service.gov.uk/company/00006400/officers",
            "https://api.company-information.service.gov.uk/company/SC123456/officers",
        ]
        assert [row["company_number"] for page in pages for row in page] == ["00006400", "SC123456"]
        manager.clear_state.assert_called_once()

    def test_paginates_one_company_until_the_total_is_reached(self) -> None:
        pages, sent, _manager_mock = _run(
            FILING_HISTORY,
            ["00006400"],
            [
                _response({"total_count": 3, "items": [{"transaction_id": "a"}, {"transaction_id": "b"}]}),
                _response({"total_count": 3, "items": [{"transaction_id": "c"}]}),
            ],
        )

        assert [params["start_index"] for _url, params in sent] == [0, 2]
        assert [row["transaction_id"] for page in pages for row in page] == ["a", "b", "c"]

    @parameterized.expand([(CHARGES,), (PERSONS_WITH_SIGNIFICANT_CONTROL,), (PSC_STATEMENTS,)])
    def test_missing_resource_does_not_fail_the_table(self, endpoint: str) -> None:
        # Companies House 404s both for "this company has nothing filed" and for an unknown
        # company number, and most companies have nothing filed for these resources.
        pages, sent, _manager_mock = _run(
            endpoint,
            ["00006400", "SC123456"],
            [_response({}, status_code=404), _response({"total_results": 1, "items": [{"id": "1"}]})],
        )

        assert len(sent) == 2
        assert [row["company_number"] for page in pages for row in page] == ["SC123456"]

    def test_auth_failure_is_not_swallowed(self) -> None:
        try:
            _run(OFFICERS, ["00006400"], [_response({}, status_code=401)])
        except HTTPError as e:
            assert e.response is not None
            assert e.response.status_code == 401
        else:
            raise AssertionError("expected the 401 to propagate")

    def test_resume_skips_completed_companies_and_seeds_the_offset(self) -> None:
        _pages, sent, _manager_mock = _run(
            OFFICERS,
            ["00006400", "SC123456", "OC301365"],
            [
                _response({"total_results": 101, "items": [{"name": "Resumed"}]}),
                _response({"total_results": 1, "items": [{"name": "Third"}]}),
            ],
            resume=UkCompaniesHouseResumeConfig(company_index=1, start_index=100),
        )

        assert [(url.rsplit("/company/", 1)[1], params["start_index"]) for url, params in sent] == [
            ("SC123456/officers", 100),
            ("OC301365/officers", 0),
        ]

    def test_saves_progress_after_each_page_and_each_company(self) -> None:
        _pages, _sent, manager = _run(
            OFFICERS,
            ["00006400", "SC123456"],
            [
                _response({"total_results": 3, "items": [{"name": "a"}, {"name": "b"}]}),
                _response({"total_results": 3, "items": [{"name": "c"}]}),
                _response({"total_results": 1, "items": [{"name": "d"}]}),
            ],
        )

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            UkCompaniesHouseResumeConfig(company_index=0, start_index=2),
            UkCompaniesHouseResumeConfig(company_index=1, start_index=0),
            UkCompaniesHouseResumeConfig(company_index=2, start_index=0),
        ]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (429, False),
            (500, False),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with patch(SESSION_TARGET) as mock_make_session:
            mock_make_session.return_value.get.return_value = _response({}, status_code=status_code)
            ok, error = validate_credentials("key", "00006400")

        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_unreachable_api_is_reported_not_raised(self) -> None:
        with patch(SESSION_TARGET) as mock_make_session:
            mock_make_session.return_value.get.side_effect = RequestException("boom")
            ok, error = validate_credentials("key", "00006400")

        assert ok is False
        assert error is not None and "Could not reach" in error
