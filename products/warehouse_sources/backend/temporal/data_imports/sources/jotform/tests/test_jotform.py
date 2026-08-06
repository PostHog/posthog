import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform import (
    JotformResumeConfig,
    _format_filter_value,
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

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the jotform module.
JOTFORM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform.make_tracked_session"
)


def _response(content: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps({"content": content, "responseCode": status_code}).encode()
    return resp


def _make_manager(resume_state: JotformResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class _Capture:
    """Snapshot each request's URL + params at prepare time (params dict is mutated in place)."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.params: list[dict[str, Any]] = []


def _wire(session: mock.MagicMock, responses: list[Response]) -> _Capture:
    session.headers = {}
    capture = _Capture()

    def _prepare(request: Any) -> mock.MagicMock:
        capture.urls.append(request.url)
        capture.params.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return capture


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return jotform_source(
        "key", "us", None, endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


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


class TestListEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_partial_page_yields_once_and_no_checkpoint(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}, {"id": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("submissions", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        # A short first page ends pagination; no next page means no checkpoint.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_partial_page_and_checkpoints_next_offset(self, MockSession):
        session = MockSession.return_value
        with mock.patch.object(JOTFORM_ENDPOINTS["submissions"], "page_size", 2):
            capture = _wire(session, [_response([{"id": "1"}, {"id": "2"}]), _response([{"id": "3"}])])
            manager = _make_manager()
            rows = _rows(_source("submissions", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert capture.params[0]["offset"] == 0
        assert capture.params[0]["limit"] == 2
        assert capture.params[1]["offset"] == 2
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == JotformResumeConfig(offset=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        capture = _wire(session, [_response([{"id": "9"}])])

        manager = _make_manager(JotformResumeConfig(offset=200))
        _rows(_source("submissions", manager))

        assert capture.params[0]["offset"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_off_still_orders_by_default_field(self, MockSession):
        session = MockSession.return_value
        capture = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("submissions", _make_manager()))

        assert capture.params[0]["orderby"] == "created_at"
        assert "filter" not in capture.params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_sends_gt_filter_on_chosen_field(self, MockSession):
        session = MockSession.return_value
        capture = _wire(session, [_response([])])

        _rows(
            _source(
                "submissions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert capture.params[0]["orderby"] == "updated_at"
        assert capture.params[0]["filter"] == '{"updated_at:gt":"2024-01-15 10:30:45"}'

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_on_without_watermark_omits_filter(self, MockSession):
        session = MockSession.return_value
        capture = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("forms", _make_manager(), should_use_incremental_field=True))

        assert capture.params[0]["orderby"] == "created_at"
        assert "filter" not in capture.params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_orderby_or_filter(self, MockSession):
        session = MockSession.return_value
        capture = _wire(session, [_response([{"id": "1"}])])

        _rows(_source("reports", _make_manager()))

        assert "orderby" not in capture.params[0]
        assert "filter" not in capture.params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_content_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source("reports", _make_manager())) == []


class TestRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_eventually_raise(self, MockSession, _sleep, status_code):
        session = MockSession.return_value
        # The client re-issues on 429/5xx; exhaust the attempts with the same status.
        _wire(session, [_response([], status_code) for _ in range(10)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("forms", _make_manager()))

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_immediately(self, MockSession, status_code):
        session = MockSession.return_value
        _wire(session, [_response([], status_code)])

        with pytest.raises(HTTPError):
            _rows(_source("forms", _make_manager()))
        # No retry on a 4xx: exactly one request was sent.
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(JOTFORM_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(JOTFORM_SESSION_PATCH)
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
    @mock.patch(JOTFORM_SESSION_PATCH)
    def test_targets_correct_host(self, mock_session, region, enterprise_domain, expected_url):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", region, enterprise_domain)
        assert mock_session.return_value.get.call_args.args[0] == expected_url

    @mock.patch(JOTFORM_SESSION_PATCH)
    def test_sends_api_key_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key-123", "us")
        assert mock_session.return_value.get.call_args.kwargs["headers"]["APIKEY"] == "key-123"

    @mock.patch(JOTFORM_SESSION_PATCH)
    def test_pins_redirects_off_and_redacts_key(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key-123", "us", "forms.acme.com")
        # User-controlled host: no redirects off the validated host, and the key is value-redacted.
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("key-123",)


class TestQuestionsFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_forms_and_injects_form_id(self, MockSession):
        session = MockSession.return_value
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        f1_questions = {"1": {"qid": "1", "text": "Name"}, "2": {"qid": "2", "text": "Email"}}
        f2_questions = {"1": {"qid": "1", "text": "Age"}}
        capture = _wire(session, [_response(forms_page), _response(f1_questions), _response(f2_questions)])

        rows = _rows(_source("questions", _make_manager()))

        assert [(row["form_id"], row["qid"]) for row in rows] == [("f1", "1"), ("f1", "2"), ("f2", "1")]
        # Forms are listed once, then each form's questions endpoint is hit in turn.
        assert capture.urls[0] == f"{US_BASE}/user/forms"
        assert capture.urls[1] == f"{US_BASE}/form/f1/questions"
        assert capture.urls[2] == f"{US_BASE}/form/f2/questions"
        assert capture.params[0]["orderby"] == "created_at"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_form_id_is_stringified(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": 42}]), _response({"1": {"qid": "1"}})])

        rows = _rows(_source("questions", _make_manager()))
        assert rows == [{"qid": "1", "form_id": "42"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_forms_without_id(self, MockSession):
        session = MockSession.return_value
        # The id-less form must not trigger a questions request.
        _wire(session, [_response([{"id": "f1"}, {"title": "no id"}]), _response({"1": {"qid": "1"}})])

        rows = _rows(_source("questions", _make_manager()))
        assert [r["form_id"] for r in rows] == ["f1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_questions_form_yields_no_rows(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "f1"}]), _response({})])

        assert _rows(_source("questions", _make_manager())) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_and_skips_completed_forms(self, MockSession):
        session = MockSession.return_value
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        f2_questions = {"1": {"qid": "1", "text": "Age"}}
        capture = _wire(session, [_response(forms_page), _response(f2_questions)])

        # f1's questions completed in the prior run; only f2 is re-fetched.
        resume = JotformResumeConfig(
            fanout_state={"completed": ["/form/f1/questions"], "current": None, "child_state": None}
        )
        rows = _rows(_source("questions", _make_manager(resume)))

        assert [(row["form_id"], row["qid"]) for row in rows] == [("f2", "1")]
        # Forms are re-listed, but f1's questions endpoint is not hit again.
        assert capture.urls == [f"{US_BASE}/user/forms", f"{US_BASE}/form/f2/questions"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_deleted_bookmark_form_restarts_from_first(self, MockSession):
        session = MockSession.return_value
        forms_page = [{"id": "f1"}, {"id": "f2"}]
        _wire(session, [_response(forms_page), _response({"1": {"qid": "1"}}), _response({"1": {"qid": "1"}})])

        resume = JotformResumeConfig(
            fanout_state={"completed": ["/form/deleted/questions"], "current": None, "child_state": None}
        )
        rows = _rows(_source("questions", _make_manager(resume)))
        assert [row["form_id"] for row in rows] == ["f1", "f2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_forms(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "f1"}]), _response({"1": {"qid": "1"}})])

        manager = _make_manager()
        _rows(_source("questions", manager))

        # The final checkpoint records f1's questions path as completed.
        saved_states = [c.args[0].fanout_state for c in manager.save_state.call_args_list]
        assert any(state and "/form/f1/questions" in (state.get("completed") or []) for state in saved_states)


class TestJotformSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = JOTFORM_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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
        if config.partition_key:
            assert config.partition_key == "created_at"

    def test_questions_primary_key_includes_form_id(self):
        assert JOTFORM_ENDPOINTS["questions"].primary_keys == ["form_id", "qid"]
