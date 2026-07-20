from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo import (
    DATAFORSEO_BASE_URL,
    MAX_PAGES_PER_TARGET,
    MAX_TARGETS,
    PAGE_SIZE,
    DataForSEOAPIError,
    DataForSEOResumeConfig,
    DataForSEORetryableError,
    _post_task,
    _raise_for_body_status,
    dataforseo_source,
    get_rows,
    parse_targets,
    validate_credentials,
    validate_targets,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.settings import (
    DATAFORSEO_ENDPOINTS,
    ENDPOINTS,
)


def _resp(body: Any, status: int = 200) -> Any:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def _body(
    results: list[dict[str, Any]] | None,
    status_code: int = 20000,
    task_status_code: int = 20000,
) -> dict[str, Any]:
    return {
        "status_code": status_code,
        "status_message": "Ok.",
        "tasks": [{"status_code": task_status_code, "status_message": "Ok.", "result": results}],
    }


def _items_result(items: list[dict[str, Any]], total_count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"target": "example.com", "items": items, "items_count": len(items)}
    if total_count is not None:
        result["total_count"] = total_count
    return result


def _manager(resume: DataForSEOResumeConfig | None = None) -> Any:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    endpoint: str,
    manager: Any,
    responses: list[Any],
    targets: list[str] | None = None,
) -> tuple[list[tuple[str, Any]], list[list[dict[str, Any]]]]:
    # Drives get_rows with a mocked tracked session, returning (posted (url, payload) pairs, batches).
    calls: list[tuple[str, Any]] = []
    response_iter = iter(responses)

    def fake_post(url: str, json: Any = None, timeout: Any = None, **_kwargs: Any) -> Any:
        calls.append((url, json[0]))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo.make_tracked_session"
    ) as MockSession:
        MockSession.return_value.post.side_effect = fake_post
        batches = list(
            get_rows(
                api_login="login",
                api_password="password",
                targets=targets or ["example.com"],
                location_name="United States",
                language_name="English",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )

    return calls, batches


class TestParseTargets:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("example.com", ["example.com"]),
            ("https://example.com/", ["example.com"]),
            ("http://www.example.com", ["example.com"]),
            ("Example.COM, example.com", ["example.com"]),
            ("a.com, b.com,, ,a.com", ["a.com", "b.com"]),
            ("app.example.com/blog", ["app.example.com/blog"]),
        ],
    )
    def test_normalizes_and_dedupes(self, raw: str, expected: list[str]) -> None:
        assert parse_targets(raw) == expected

    def test_empty_input_is_an_error(self) -> None:
        parsed, error = validate_targets("  , ")
        assert parsed == []
        assert error is not None

    def test_too_many_targets_is_an_error(self) -> None:
        raw = ", ".join(f"site{i}.com" for i in range(MAX_TARGETS + 1))
        _, error = validate_targets(raw)
        assert error is not None
        assert str(MAX_TARGETS) in error

    def test_max_targets_is_allowed(self) -> None:
        raw = ", ".join(f"site{i}.com" for i in range(MAX_TARGETS))
        parsed, error = validate_targets(raw)
        assert error is None
        assert len(parsed) == MAX_TARGETS


class TestBodyStatusClassification:
    @pytest.mark.parametrize("status_code", [None, 20000])
    def test_success_codes_pass(self, status_code: int | None) -> None:
        _raise_for_body_status(status_code, "Ok.")

    @pytest.mark.parametrize("status_code", [40202, 50000, 50401])
    def test_transient_codes_raise_retryable(self, status_code: int) -> None:
        with pytest.raises(DataForSEORetryableError):
            _raise_for_body_status(status_code, "try again")

    @pytest.mark.parametrize("status_code", [40100, 40200, 40201, 40203, 40210, 40501])
    def test_permanent_codes_raise_api_error_with_code(self, status_code: int) -> None:
        with pytest.raises(DataForSEOAPIError, match=rf"\[{status_code}\]"):
            _raise_for_body_status(status_code, "nope")


class TestPostTask:
    # Exercise a single attempt via __wrapped__ so the tenacity retry loop (and its real
    # backoff sleeps) is not driven.
    def _post(self, response: Any) -> list[dict[str, Any]]:
        session = MagicMock()
        session.post.return_value = response
        return _post_task.__wrapped__(
            session, "/dataforseo_labs/google/ranked_keywords/live", {"target": "example.com"}, MagicMock()
        )

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_http_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(DataForSEORetryableError):
            self._post(_resp({}, status=status))

    def test_client_error_raises_http_error(self) -> None:
        response = _resp({}, status=401)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        with pytest.raises(requests.HTTPError):
            self._post(response)

    def test_top_level_error_code_raises(self) -> None:
        with pytest.raises(DataForSEOAPIError, match=r"\[40100\]"):
            self._post(_resp({"status_code": 40100, "status_message": "unauthorized", "tasks": []}))

    def test_task_level_error_code_raises(self) -> None:
        with pytest.raises(DataForSEOAPIError, match=r"\[40501\]"):
            self._post(_resp(_body(None, task_status_code=40501)))

    @pytest.mark.parametrize("results", [None, []])
    def test_missing_result_returns_empty(self, results: Any) -> None:
        assert self._post(_resp(_body(results))) == []

    def test_wraps_payload_in_array(self) -> None:
        session = MagicMock()
        session.post.return_value = _resp(_body([]))
        _post_task.__wrapped__(session, "/path", {"target": "example.com"}, MagicMock())
        _, kwargs = session.post.call_args
        assert kwargs["json"] == [{"target": "example.com"}]


class TestGetRows:
    def test_items_endpoint_injects_target(self) -> None:
        manager = _manager()
        responses = [_resp(_body([_items_result([{"se_type": "google", "metrics": {}}])]))]

        calls, batches = _drive("domain_rank_overview", manager, responses)

        assert calls[0][0] == f"{DATAFORSEO_BASE_URL}/dataforseo_labs/google/domain_rank_overview/live"
        assert batches == [[{"se_type": "google", "metrics": {}, "target": "example.com"}]]

    def test_localized_payload_carries_location_and_language(self) -> None:
        manager = _manager()
        calls, _ = _drive("domain_rank_overview", manager, [_resp(_body([_items_result([])]))])

        payload = calls[0][1]
        assert payload["location_name"] == "United States"
        assert payload["language_name"] == "English"

    def test_backlinks_payload_has_no_location_and_includes_subdomains(self) -> None:
        manager = _manager()
        summary = {"target": "example.com", "rank": 312, "backlinks": 100}
        calls, batches = _drive("backlinks_summary", manager, [_resp(_body([summary]))])

        payload = calls[0][1]
        assert "location_name" not in payload
        assert payload["include_subdomains"] is True
        assert batches == [[{**summary, "target": "example.com"}]]

    def test_historical_payload_requests_full_history_and_rows_carry_date(self) -> None:
        manager = _manager()
        items = [{"year": 2024, "month": 3, "metrics": {}}, {"year": 2024, "month": 11, "metrics": {}}]
        calls, batches = _drive("historical_rank_overview", manager, [_resp(_body([_items_result(items)]))])

        assert calls[0][1]["date_from"] == "2020-10-01"
        assert [row["date"] for row in batches[0]] == ["2024-03-01", "2024-11-01"]

    def test_ranked_keywords_flattens_key_fields(self) -> None:
        manager = _manager()
        item = {
            "se_type": "google",
            "keyword_data": {"keyword": "posthog", "keyword_info": {"search_volume": 1000}},
            "ranked_serp_element": {
                "serp_item": {"type": "organic", "rank_group": 2, "rank_absolute": 3, "url": "https://example.com/x"}
            },
        }
        _, batches = _drive("ranked_keywords", manager, [_resp(_body([_items_result([item], total_count=1)]))])

        row = batches[0][0]
        assert row["keyword"] == "posthog"
        assert row["item_type"] == "organic"
        assert row["rank_group"] == 2
        assert row["rank_absolute"] == 3
        assert row["ranked_url"] == "https://example.com/x"
        assert row["target"] == "example.com"
        assert row["keyword_data"] == item["keyword_data"]

    def test_ranked_keywords_skips_items_without_keyword(self) -> None:
        manager = _manager()
        items = [{"keyword_data": {}}, {"keyword_data": {"keyword": "ok"}}]
        _, batches = _drive("ranked_keywords", manager, [_resp(_body([_items_result(items, total_count=2)]))])

        assert [row["keyword"] for row in batches[0]] == ["ok"]

    def test_paginates_by_total_count_and_saves_state_after_each_page(self) -> None:
        manager = _manager()
        page_1 = [{"keyword_data": {"keyword": f"kw{i}"}} for i in range(PAGE_SIZE)]
        page_2 = [{"keyword_data": {"keyword": "last"}}]
        responses = [
            _resp(_body([_items_result(page_1, total_count=PAGE_SIZE + 1)])),
            _resp(_body([_items_result(page_2, total_count=PAGE_SIZE + 1)])),
        ]

        calls, batches = _drive("ranked_keywords", manager, responses)

        assert [payload["offset"] for _, payload in calls] == [0, PAGE_SIZE]
        assert all(payload["limit"] == PAGE_SIZE for _, payload in calls)
        assert len(batches) == 2
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DataForSEOResumeConfig(target="example.com", offset=PAGE_SIZE)]

    def test_pagination_stops_at_page_cap(self) -> None:
        manager = _manager()
        logger = MagicMock()
        full_page = [{"keyword_data": {"keyword": f"kw{i}"}} for i in range(PAGE_SIZE)]
        responses = [
            _resp(_body([_items_result(full_page, total_count=PAGE_SIZE * 100)])) for _ in range(MAX_PAGES_PER_TARGET)
        ]

        calls: list[tuple[str, Any]] = []
        response_iter = iter(responses)

        def fake_post(url: str, json: Any = None, timeout: Any = None, **_kwargs: Any) -> Any:
            calls.append((url, json[0]))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.post.side_effect = fake_post
            batches = list(
                get_rows(
                    api_login="login",
                    api_password="password",
                    targets=["example.com"],
                    location_name="United States",
                    language_name="English",
                    endpoint="ranked_keywords",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert len(calls) == MAX_PAGES_PER_TARGET
        assert len(batches) == MAX_PAGES_PER_TARGET
        logger.warning.assert_called_once()

    def test_fans_out_over_targets_and_saves_next_target_state(self) -> None:
        manager = _manager()
        responses = [
            _resp(_body([_items_result([{"se_type": "google"}])])),
            _resp(_body([_items_result([{"se_type": "google"}])])),
        ]

        calls, batches = _drive("domain_rank_overview", manager, responses, targets=["a.com", "b.com"])

        assert [payload["target"] for _, payload in calls] == ["a.com", "b.com"]
        assert [row["target"] for batch in batches for row in batch] == ["a.com", "b.com"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DataForSEOResumeConfig(target="b.com", offset=0)]

    def test_resume_skips_earlier_targets_and_seeds_offset(self) -> None:
        manager = _manager(DataForSEOResumeConfig(target="b.com", offset=PAGE_SIZE))
        responses = [_resp(_body([_items_result([{"keyword_data": {"keyword": "kw"}}], total_count=1)]))]

        calls, _ = _drive("ranked_keywords", manager, responses, targets=["a.com", "b.com"])

        assert len(calls) == 1
        assert calls[0][1]["target"] == "b.com"
        assert calls[0][1]["offset"] == PAGE_SIZE

    def test_resume_with_removed_target_starts_over(self) -> None:
        manager = _manager(DataForSEOResumeConfig(target="gone.com", offset=PAGE_SIZE))
        responses = [_resp(_body([_items_result([])]))]

        calls, _ = _drive("domain_rank_overview", manager, responses, targets=["a.com"])

        assert calls[0][1]["target"] == "a.com"

    def test_empty_result_yields_nothing(self) -> None:
        manager = _manager()
        _, batches = _drive("domain_rank_overview", manager, [_resp(_body([_items_result([])]))])

        assert batches == []

    def test_session_carries_basic_auth_and_redacts_password(self) -> None:
        manager = _manager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.post.return_value = _resp(_body([_items_result([])]))
            list(
                get_rows(
                    api_login="login",
                    api_password="password",
                    targets=["example.com"],
                    location_name="United States",
                    language_name="English",
                    endpoint="domain_rank_overview",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        _, kwargs = MockSession.call_args
        assert kwargs["headers"]["Authorization"].startswith("Basic ")
        assert "password" in kwargs["redact_values"]


class TestDataForSEOSourceResponse:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape(self, endpoint: str) -> None:
        response = dataforseo_source(
            api_login="login",
            api_password="password",
            targets=["example.com"],
            location_name="United States",
            language_name="English",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        config = DATAFORSEO_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_primary_keys_include_target(self, endpoint: str) -> None:
        # Every endpoint fans out over the configured targets, so the injected target must be
        # part of the key for table-wide uniqueness.
        assert "target" in DATAFORSEO_ENDPOINTS[endpoint].primary_keys


class TestValidateCredentials:
    def _validate(self, response: Any = None, raises: Exception | None = None) -> bool:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo.make_tracked_session"
        ) as MockSession:
            get = MockSession.return_value.get
            if raises is not None:
                get.side_effect = raises
            else:
                get.return_value = response
            return validate_credentials("login", "password")

    def test_valid_credentials(self) -> None:
        assert self._validate(_resp({"status_code": 20000, "tasks": []})) is True

    def test_unauthorized_is_invalid(self) -> None:
        assert self._validate(_resp({}, status=401)) is False

    def test_error_body_is_invalid(self) -> None:
        assert self._validate(_resp({"status_code": 40100, "status_message": "unauthorized"})) is False

    def test_network_error_is_invalid(self) -> None:
        assert self._validate(raises=requests.ConnectionError("boom")) is False

    @pytest.mark.parametrize(("login", "password"), [("", "password"), ("login", ""), (" ", " ")])
    def test_blank_credentials_are_invalid_without_a_request(self, login: str, password: str) -> None:
        assert validate_credentials(login, password) is False
