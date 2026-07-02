from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform import (
    JotformResumeConfig,
    JotformRetryableError,
    _build_list_params,
    _format_filter_value,
    _question_row,
    get_form_ids,
    get_rows,
    jotform_source,
    normalize_enterprise_host,
    resolve_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    ENDPOINTS,
    JOTFORM_ENDPOINTS,
)

US_BASE = "https://api.jotform.com"


def _make_manager(resume_state: JotformResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(content: Any, status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = {"content": content, "responseCode": status_code}
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = ""
    return response


def _params(call: mock.Mock) -> dict[str, Any]:
    return call.kwargs["params"]


class TestResolveBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.jotform.com"),
            ("eu", "https://eu-api.jotform.com"),
            ("hipaa", "https://hipaa-api.jotform.com"),
            ("US", "https://api.jotform.com"),
            ("unknown", "https://api.jotform.com"),
            (None, "https://api.jotform.com"),
        ],
    )
    def test_region_hosts(self, region, expected):
        assert resolve_base_url(region) == expected

    @pytest.mark.parametrize(
        "domain, expected",
        [
            ("forms.acme.com", "https://forms.acme.com/API"),
            ("https://forms.acme.com", "https://forms.acme.com/API"),
            ("http://forms.acme.com/", "https://forms.acme.com/API"),
            ("  forms.acme.com/  ", "https://forms.acme.com/API"),
        ],
    )
    def test_enterprise_domain_overrides_region(self, domain, expected):
        # Enterprise domain wins over the region selection and is served under /API.
        assert resolve_base_url("eu", domain) == expected

    @pytest.mark.parametrize("domain", ["", "   ", None])
    def test_blank_enterprise_domain_falls_back_to_region(self, domain):
        assert resolve_base_url("eu", domain) == "https://eu-api.jotform.com"

    @pytest.mark.parametrize(
        "domain, expected",
        [("forms.acme.com", "forms.acme.com"), ("https://forms.acme.com/", "forms.acme.com"), ("", None), (None, None)],
    )
    def test_normalize_enterprise_host(self, domain, expected):
        assert normalize_enterprise_host(domain) == expected


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC), "2024-01-15 10:30:45"),
            (datetime(2024, 1, 15, 10, 30, 45), "2024-01-15 10:30:45"),
            (date(2024, 1, 15), "2024-01-15 00:00:00"),
            ("2024-01-15 10:30:45", "2024-01-15 10:30:45"),
            ("2024-01-15T10:30:45", "2024-01-15 10:30:45"),
            (None, None),
            (True, None),
            ("not-a-date", None),
        ],
    )
    def test_format(self, value, expected):
        assert _format_filter_value(value) == expected

    def test_future_value_is_capped_to_now(self):
        future = datetime.now(UTC) + timedelta(days=365)
        formatted = _format_filter_value(future)
        assert formatted is not None
        assert datetime.strptime(formatted, "%Y-%m-%d %H:%M:%S") <= datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=2
        )


class TestBuildListParams:
    def test_full_refresh_endpoint_has_no_params(self):
        # reports has no incremental fields, so no orderby/filter is sent.
        assert _build_list_params(JOTFORM_ENDPOINTS["reports"], False, None, None) == {}

    def test_incremental_off_still_orders_by_default_field(self):
        params = _build_list_params(JOTFORM_ENDPOINTS["submissions"], False, None, None)
        assert params == {"orderby": "created_at"}
        assert "filter" not in params

    def test_incremental_on_adds_gt_filter_on_chosen_field(self):
        params = _build_list_params(
            JOTFORM_ENDPOINTS["submissions"], True, datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC), "updated_at"
        )
        assert params["orderby"] == "updated_at"
        assert params["filter"] == '{"updated_at:gt":"2024-01-15 10:30:45"}'

    def test_incremental_on_without_watermark_omits_filter(self):
        params = _build_list_params(JOTFORM_ENDPOINTS["forms"], True, None, None)
        assert params == {"orderby": "created_at"}


class TestFetchPageRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_retryable_statuses_eventually_raise(self, mock_session, _sleep, status_code):
        mock_session.return_value.get.return_value = _response([], status_code)
        manager = _make_manager()
        with pytest.raises(JotformRetryableError):
            list(get_rows("key", "us", None, "forms", mock.MagicMock(), manager))

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_client_errors_raise_immediately(self, mock_session, status_code):
        response = _response([], status_code)
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
        mock_session.return_value.get.return_value = response
        manager = _make_manager()
        with pytest.raises(requests.HTTPError):
            list(get_rows("key", "us", None, "forms", mock.MagicMock(), manager))


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response("", status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @pytest.mark.parametrize(
        "region, enterprise_domain, expected_url",
        [
            ("us", None, "https://api.jotform.com/user"),
            ("eu", None, "https://eu-api.jotform.com/user"),
            ("us", "forms.acme.com", "https://forms.acme.com/API/user"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_targets_correct_host(self, mock_session, region, enterprise_domain, expected_url):
        mock_session.return_value.get.return_value = _response("", 200)
        validate_credentials("key", region, enterprise_domain)
        assert mock_session.return_value.get.call_args.args[0] == expected_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_sends_api_key_header(self, mock_session):
        mock_session.return_value.get.return_value = _response("", 200)
        validate_credentials("key-123", "us")
        assert mock_session.return_value.get.call_args.kwargs["headers"]["APIKEY"] == "key-123"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_pins_redirects_off_and_redacts_key(self, mock_session):
        mock_session.return_value.get.return_value = _response("", 200)
        validate_credentials("key-123", "us", "forms.acme.com")
        # User-controlled host: no redirects off the validated host, and the key is value-redacted.
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("key-123",)


class TestGetFormIds:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_paginates_across_offset_pages(self, mock_session):
        page_size = JOTFORM_ENDPOINTS["forms"].page_size
        full = [{"id": f"f{i}"} for i in range(page_size)]
        partial = [{"id": "last"}]
        mock_session.return_value.get.side_effect = [_response(full), _response(partial)]

        ids = get_form_ids(US_BASE, {"APIKEY": "key"}, mock.MagicMock())

        assert len(ids) == page_size + 1
        assert ids[-1] == "last"
        assert _params(mock_session.return_value.get.call_args_list[1])["offset"] == page_size

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_skips_items_without_id_and_stringifies(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": 42}, {"title": "no id"}])
        assert get_form_ids(US_BASE, {}, mock.MagicMock()) == ["42"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_pins_redirects_off_and_redacts_key(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "1"}])
        get_form_ids(US_BASE, {"APIKEY": "secret-key"}, mock.MagicMock())
        # Page fetches against a potentially user-controlled host must not follow redirects, and the
        # key carried in the APIKEY header is value-redacted from logs.
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestGetRowsListEndpoints:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_single_partial_page_yields_once_and_saves_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "1"}, {"id": "2"}])

        manager = _make_manager()
        batches = list(get_rows("key", "us", None, "submissions", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2"]
        saved = [c.args[0].offset for c in manager.save_state.call_args_list]
        assert saved == [0]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_paginates_until_partial_page(self, mock_session):
        with mock.patch.object(JOTFORM_ENDPOINTS["submissions"], "page_size", 2):
            mock_session.return_value.get.side_effect = [
                _response([{"id": "1"}, {"id": "2"}]),
                _response([{"id": "3"}]),
            ]

            manager = _make_manager()
            batches = list(get_rows("key", "us", None, "submissions", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        # Offset advances by page_size between pages; state saved after each yielded page.
        assert _params(mock_session.return_value.get.call_args_list[1])["offset"] == 2
        assert [c.args[0].offset for c in manager.save_state.call_args_list] == [0, 2]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        manager = _make_manager(JotformResumeConfig(offset=200))
        list(get_rows("key", "us", None, "submissions", mock.MagicMock(), manager))

        assert _params(mock_session.return_value.get.call_args_list[0])["offset"] == 200

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_incremental_run_sends_gt_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "us",
                None,
                "submissions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        params = _params(mock_session.return_value.get.call_args_list[0])
        assert params["orderby"] == "created_at"
        assert params["filter"] == '{"created_at:gt":"2024-01-15 10:30:45"}'

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_empty_content_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        assert list(get_rows("key", "us", None, "reports", mock.MagicMock(), manager)) == []


class TestGetRowsQuestionsFanOut:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_fans_out_over_forms_and_injects_form_id(self, mock_session):
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        f1_questions = {"1": {"qid": "1", "text": "Name"}, "2": {"qid": "2", "text": "Email"}}
        f2_questions = {"1": {"qid": "1", "text": "Age"}}
        mock_session.return_value.get.side_effect = [
            _response(forms_page),
            _response(f1_questions),
            _response(f2_questions),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "us", None, "questions", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [(row["form_id"], row["qid"]) for row in rows] == [("f1", "1"), ("f1", "2"), ("f2", "1")]
        # The form id is fetched then each form's questions endpoint is hit.
        assert mock_session.return_value.get.call_args_list[1].args[0] == f"{US_BASE}/form/f1/questions"
        assert [c.args[0].form_id for c in manager.save_state.call_args_list] == ["f1", "f2"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_resumes_from_bookmarked_form(self, mock_session):
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        f2_questions = {"1": {"qid": "1", "text": "Age"}}
        mock_session.return_value.get.side_effect = [_response(forms_page), _response(f2_questions)]

        manager = _make_manager(JotformResumeConfig(form_id="f2"))
        batches = list(get_rows("key", "us", None, "questions", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        # f1 was completed in the prior run; only f2 is re-fetched.
        assert [(row["form_id"], row["qid"]) for row in rows] == [("f2", "1")]
        assert mock_session.return_value.get.call_args_list[1].args[0] == f"{US_BASE}/form/f2/questions"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session")
    def test_deleted_bookmark_form_restarts_from_first(self, mock_session):
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        mock_session.return_value.get.side_effect = [
            _response(forms_page),
            _response({"1": {"qid": "1"}}),
            _response({"1": {"qid": "1"}}),
        ]

        manager = _make_manager(JotformResumeConfig(form_id="deleted-form"))
        batches = list(get_rows("key", "us", None, "questions", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [row["form_id"] for row in rows] == ["f1", "f2"]

    def test_question_row_injects_form_id(self):
        assert _question_row("f9", {"qid": "3", "text": "Q"}) == {"qid": "3", "text": "Q", "form_id": "f9"}

    def test_question_row_does_not_mutate_input(self):
        question = {"qid": "3"}
        _question_row("f9", question)
        assert question == {"qid": "3"}


class TestJotformSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = JOTFORM_ENDPOINTS[endpoint]
        response = jotform_source("key", "us", None, endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_format == config.partition_format
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(JOTFORM_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Partitioning must never key off an updated_at-style field that rewrites on every sync.
        if config.partition_key:
            assert config.partition_key == "created_at"

    def test_questions_primary_key_includes_form_id(self):
        # qid is unique only within a form, so the table-wide key needs form_id.
        assert JOTFORM_ENDPOINTS["questions"].primary_keys == ["form_id", "qid"]
