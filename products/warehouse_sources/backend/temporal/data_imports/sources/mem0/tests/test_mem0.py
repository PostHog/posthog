from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mem0 import mem0 as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0 import (
    _MATCH_ALL_FILTER,
    Mem0ResumeConfig,
    get_rows,
    mem0_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENTITIES_ENDPOINT,
    EVENTS_ENDPOINT,
    MEM0_BASE_URL,
    MEMORIES_ENDPOINT,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0"


def _response(payload: Any = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload if payload is not None else {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: Unauthorized for url: {MEM0_BASE_URL}/v3/memories/", response=response
        )
    return response


def _manager(resume: Mem0ResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False)])
    @patch(f"{_MODULE}.make_tracked_session")
    def test_maps_status_code_to_validity(self, status_code, expected, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        assert validate_credentials("m0-test") is expected

    @patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_is_invalid_not_raised(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("m0-test") is False

    @patch(f"{_MODULE}.make_tracked_session")
    def test_probes_the_ping_endpoint_with_token_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("m0-test")

        args, kwargs = mock_session.return_value.get.call_args
        assert args[0] == f"{MEM0_BASE_URL}/v1/ping/"
        assert kwargs["headers"]["Authorization"] == "Token m0-test"


class TestMemoriesRows:
    @patch(f"{_MODULE}.make_tracked_session")
    def test_yields_every_page_and_terminates_on_null_next(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response(
                {"count": 3, "next": "https://api.mem0.ai/v3/memories/?page=2", "results": [{"id": "m1"}, {"id": "m2"}]}
            ),
            _response({"count": 3, "next": None, "results": [{"id": "m3"}]}),
        ]

        batches = list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), _manager()))

        assert batches == [[{"id": "m1"}, {"id": "m2"}], [{"id": "m3"}]]
        urls = [call.args[1] for call in mock_session.return_value.request.call_args_list]
        assert "page=1" in urls[0] and "page=2" in urls[1]
        assert all("page_size=100" in url for url in urls)

    @patch(f"{_MODULE}.make_tracked_session")
    def test_full_sync_sends_wildcard_filter_over_every_entity_type(self, mock_session):
        # A bare {"user_id": "*"} filter would silently drop memories scoped only to an
        # agent, app, or run; the request must OR the wildcard across all four entity ids.
        mock_session.return_value.request.return_value = _response({"next": None, "results": []})

        list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), _manager()))

        body = mock_session.return_value.request.call_args.kwargs["json"]
        assert body == {"filters": _MATCH_ALL_FILTER}
        assert {"agent_id": "*"} in body["filters"]["OR"]

    @patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_sync_filters_on_the_users_chosen_field(self, mock_session):
        mock_session.return_value.request.return_value = _response({"next": None, "results": []})

        list(
            get_rows(
                "m0-test",
                MEMORIES_ENDPOINT,
                MagicMock(),
                _manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 7, 1, 12, 30, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        body = mock_session.return_value.request.call_args.kwargs["json"]
        assert body == {"filters": {"AND": [_MATCH_ALL_FILTER, {"created_at": {"gte": "2026-07-01"}}]}}

    @patch(f"{_MODULE}.make_tracked_session")
    def test_saves_resume_state_only_after_yielding_and_only_when_pages_remain(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response({"next": "https://api.mem0.ai/v3/memories/?page=2", "results": [{"id": "m1"}]}),
            _response({"next": None, "results": [{"id": "m2"}]}),
        ]
        manager = _manager()

        list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), manager))

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved == Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, page=2, cutoff=None)

    @patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_page_and_pins_the_original_cutoff(self, mock_session):
        # The saved cutoff (not a freshly computed one) must drive the filter on resume,
        # otherwise the resumed run paginates a different server-side result set and the
        # page number no longer lines up.
        mock_session.return_value.request.return_value = _response({"next": None, "results": []})
        manager = _manager(Mem0ResumeConfig(endpoint=MEMORIES_ENDPOINT, page=3, cutoff="2026-06-01"))

        list(
            get_rows(
                "m0-test",
                MEMORIES_ENDPOINT,
                MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 7, 10, tzinfo=UTC),
            )
        )

        call = mock_session.return_value.request.call_args
        assert "page=3" in call.args[1]
        assert call.kwargs["json"] == {"filters": {"AND": [_MATCH_ALL_FILTER, {"updated_at": {"gte": "2026-06-01"}}]}}

    @patch(f"{_MODULE}.make_tracked_session")
    def test_ignores_resume_state_saved_by_a_different_endpoint(self, mock_session):
        mock_session.return_value.request.return_value = _response({"next": None, "results": []})
        manager = _manager(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url="https://api.mem0.ai/v1/events/?page=9"))

        list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), manager))

        assert "page=1" in mock_session.return_value.request.call_args.args[1]


class TestCutoffFormatting:
    @parameterized.expand(
        [
            (datetime(2026, 7, 1, 23, 59, tzinfo=UTC), "2026-07-01"),
            (datetime(2026, 7, 1, 12, 0), "2026-07-01"),  # naive treated as UTC
            (date(2026, 7, 1), "2026-07-01"),
            ("2026-07-01", "2026-07-01"),
            (None, None),
        ]
    )
    def test_formats_cursor_as_date_string(self, value, expected):
        assert api_client._format_cutoff(value) == expected


class TestEntitiesRows:
    @patch(f"{_MODULE}.make_tracked_session")
    def test_yields_the_bare_array_response(self, mock_session):
        mock_session.return_value.request.return_value = _response([{"id": "alex", "type": "user"}])

        batches = list(get_rows("m0-test", ENTITIES_ENDPOINT, MagicMock(), _manager()))

        assert batches == [[{"id": "alex", "type": "user"}]]
        assert mock_session.return_value.request.call_args.args == ("GET", f"{MEM0_BASE_URL}/v1/entities/")

    @patch(f"{_MODULE}.make_tracked_session")
    def test_tolerates_an_enveloped_response(self, mock_session):
        mock_session.return_value.request.return_value = _response({"results": [{"id": "alex"}]})

        batches = list(get_rows("m0-test", ENTITIES_ENDPOINT, MagicMock(), _manager()))

        assert batches == [[{"id": "alex"}]]

    @parameterized.expand(
        [
            ("org_only", "org_1", None, "org_id=org_1"),
            ("project_only", None, "proj_1", "project_id=proj_1"),
            ("both", "org_1", "proj_1", "org_id=org_1&project_id=proj_1"),
        ]
    )
    @patch(f"{_MODULE}.make_tracked_session")
    def test_scopes_listing_with_org_and_project_params(self, _name, org_id, project_id, expected_query, mock_session):
        mock_session.return_value.request.return_value = _response([])

        list(get_rows("m0-test", ENTITIES_ENDPOINT, MagicMock(), _manager(), org_id=org_id, project_id=project_id))

        url = mock_session.return_value.request.call_args.args[1]
        assert url == f"{MEM0_BASE_URL}/v1/entities/?{expected_query}"


class TestEventsRows:
    @patch(f"{_MODULE}.make_tracked_session")
    def test_follows_next_urls_and_checkpoints_after_each_yield(self, mock_session):
        mock_session.return_value.request.side_effect = [
            _response({"next": f"{MEM0_BASE_URL}/v1/events/?page=2", "results": [{"id": "e1"}]}),
            _response({"next": None, "results": [{"id": "e2"}]}),
        ]
        manager = _manager()

        batches = list(get_rows("m0-test", EVENTS_ENDPOINT, MagicMock(), manager))

        assert batches == [[{"id": "e1"}], [{"id": "e2"}]]
        manager.save_state.assert_called_once_with(
            Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=f"{MEM0_BASE_URL}/v1/events/?page=2")
        )

    @patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_the_saved_next_url(self, mock_session):
        mock_session.return_value.request.return_value = _response({"next": None, "results": []})
        manager = _manager(Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url=f"{MEM0_BASE_URL}/v1/events/?page=5"))

        list(get_rows("m0-test", EVENTS_ENDPOINT, MagicMock(), manager))

        assert mock_session.return_value.request.call_args.args[1] == f"{MEM0_BASE_URL}/v1/events/?page=5"

    @parameterized.expand(
        [
            ("absolute", "https://evil.example.com/v1/events/?page=2"),
            ("scheme_relative", "//evil.example.com/v1/events/?page=2"),
            ("non_https", "http://api.mem0.ai/v1/events/?page=2"),
            ("lookalike_host", "https://api.mem0.ai.evil.example.com/v1/events/?page=2"),
        ]
    )
    @patch(f"{_MODULE}.make_tracked_session")
    def test_refuses_to_follow_off_origin_next_links(self, _name, next_url, mock_session):
        # The session carries the API key; a tampered `next` link must never receive a
        # credentialed request or be persisted as resume state.
        mock_session.return_value.request.return_value = _response({"next": next_url, "results": [{"id": "e1"}]})
        manager = _manager()

        try:
            list(get_rows("m0-test", EVENTS_ENDPOINT, MagicMock(), manager))
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

        assert mock_session.return_value.request.call_count == 1
        manager.save_state.assert_not_called()

    @patch(f"{_MODULE}.make_tracked_session")
    def test_refuses_to_resume_from_an_off_origin_saved_url(self, mock_session):
        manager = _manager(
            Mem0ResumeConfig(endpoint=EVENTS_ENDPOINT, next_url="https://evil.example.com/v1/events/?page=5")
        )

        try:
            list(get_rows("m0-test", EVENTS_ENDPOINT, MagicMock(), manager))
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

        mock_session.return_value.request.assert_not_called()


class TestFetchRetry:
    @patch("tenacity.nap.time.sleep", return_value=None)
    @patch(f"{_MODULE}.make_tracked_session")
    def test_retries_rate_limits_then_succeeds(self, mock_session, _sleep):
        mock_session.return_value.request.side_effect = [
            _response({}, status_code=429),
            _response({"next": None, "results": [{"id": "m1"}]}),
        ]

        batches = list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), _manager()))

        assert batches == [[{"id": "m1"}]]
        assert mock_session.return_value.request.call_count == 2

    @patch(f"{_MODULE}.make_tracked_session")
    def test_auth_errors_raise_immediately_without_retry(self, mock_session):
        mock_session.return_value.request.return_value = _response({}, status_code=401)

        try:
            list(get_rows("m0-test", MEMORIES_ENDPOINT, MagicMock(), _manager()))
            raise AssertionError("expected HTTPError")
        except requests.HTTPError:
            pass

        assert mock_session.return_value.request.call_count == 1


class TestMem0SourceResponse:
    def test_memories_response_merges_on_id_and_partitions_on_stable_created_at(self):
        response = mem0_source("m0-test", MEMORIES_ENDPOINT, MagicMock(), _manager())

        assert response.name == MEMORIES_ENDPOINT
        assert response.primary_keys == ["id"]
        # The list endpoint has no sort parameter, so ordering is undefined; "desc" defers
        # the incremental watermark commit to successful end of run.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_entities_response_has_no_partitioning(self):
        response = mem0_source("m0-test", ENTITIES_ENDPOINT, MagicMock(), _manager())

        assert response.partition_mode is None
        assert response.partition_keys is None
