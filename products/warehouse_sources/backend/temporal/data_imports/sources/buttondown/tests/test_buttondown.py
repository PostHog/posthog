import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.buttondown import (
    BUTTONDOWN_API_VERSION,
    BUTTONDOWN_BASE_URL,
    ButtondownResumeConfig,
    _to_start_date,
    buttondown_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import BUTTONDOWN_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
BUTTONDOWN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.buttondown.make_tracked_session"
)


def _response(results: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_results: bool = False):
    body: dict[str, Any] = {"count": 1, "next": next_url, "previous": None}
    if not drop_results:
        body["results"] = results or []
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: ButtondownResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class _Wired:
    def __init__(self) -> None:
        self.params: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.auths: list[Any] = []


def _wire(session: mock.MagicMock, responses: list[Response]) -> _Wired:
    # `request.params`/`request.url` are mutated in place across pages, so snapshot them when each
    # request is prepared rather than reading the final state after the run.
    session.headers = {}
    wired = _Wired()

    def _prepare(request: Any) -> mock.MagicMock:
        wired.params.append(dict(request.params or {}))
        wired.urls.append(request.url)
        wired.auths.append(request.auth)
        return mock.MagicMock(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return wired


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses: list[Response], manager: mock.MagicMock | None = None, **kwargs):
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        wired = _wire(session, responses)
        response = buttondown_source(
            "bd-key",
            endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager or _make_manager(),
            **kwargs,
        )
        rows = _rows(response)
    return rows, wired, response, session


class TestButtondownTransport:
    def test_follows_next_link_until_null(self) -> None:
        page_two = f"{BUTTONDOWN_BASE_URL}/subscribers?page=2"
        rows, wired, _, _ = _run(
            "subscribers",
            [_response([{"id": "a"}], next_url=page_two), _response([{"id": "b"}], next_url=None)],
        )

        assert [row["id"] for row in rows] == ["a", "b"]
        assert wired.urls[1] == page_two
        # The next link is self-contained; re-sending the original params would duplicate them.
        assert wired.params[1] == {}

    def test_checkpoints_only_while_a_next_page_remains(self) -> None:
        page_two = f"{BUTTONDOWN_BASE_URL}/subscribers?page=2"
        manager = _make_manager()
        _run(
            "subscribers",
            [_response([{"id": "a"}], next_url=page_two), _response([{"id": "b"}], next_url=None)],
            manager,
        )

        manager.save_state.assert_called_once_with(ButtondownResumeConfig(next_url=page_two))

    def test_resumes_from_saved_next_url(self) -> None:
        saved = f"{BUTTONDOWN_BASE_URL}/subscribers?page=7"
        rows, wired, _, session = _run(
            "subscribers",
            [_response([{"id": "z"}], next_url=None)],
            _make_manager(ButtondownResumeConfig(next_url=saved)),
        )

        assert wired.urls[0] == saved
        assert session.send.call_count == 1
        assert [row["id"] for row in rows] == ["z"]

    def test_sends_token_prefixed_key_and_version_header(self) -> None:
        _, wired, _, session = _run("subscribers", [_response([{"id": "a"}])])

        prepared = PreparedRequest()
        prepared.prepare(method="GET", url=f"{BUTTONDOWN_BASE_URL}/subscribers")
        wired.auths[0](prepared)
        # Buttondown rejects a "Bearer " prefix, so this is the difference between syncing and 401ing.
        assert prepared.headers["Authorization"] == "Token bd-key"
        assert session.headers.get("X-API-Version") == BUTTONDOWN_API_VERSION

    def test_api_version_header_is_overridable(self) -> None:
        _, _, _, session = _run("subscribers", [_response([{"id": "a"}])], api_version="2025-01-02")

        assert session.headers.get("X-API-Version") == "2025-01-02"

    @pytest.mark.parametrize(
        "endpoint,expected_param",
        [
            ("subscribers", "date__start"),
            ("emails", "creation_date__start"),
            ("survey_responses", "creation_date__start"),
        ],
    )
    def test_incremental_sync_sends_the_server_side_date_filter(self, endpoint: str, expected_param: str) -> None:
        _, wired, _, _ = _run(
            endpoint,
            [_response([{"id": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 15, 30),
        )

        # One day back from the watermark: the docs don't say whether the bound is inclusive, and
        # overlapping rows merge away while a missed day would be silent data loss.
        assert wired.params[0][expected_param] == "2026-03-03"

    @pytest.mark.parametrize("endpoint", ["subscribers", "emails", "survey_responses"])
    def test_full_refresh_sends_no_date_filter(self, endpoint: str) -> None:
        _, wired, _, _ = _run(
            endpoint,
            [_response([{"id": "a"}])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4),
        )

        assert not [key for key in wired.params[0] if key.endswith("__start")]

    @pytest.mark.parametrize("endpoint", ["subscribers", "emails", "survey_responses"])
    @pytest.mark.parametrize("watermark", [None, "not-a-date"], ids=["missing", "unparseable"])
    def test_incremental_without_a_usable_watermark_sends_no_date_filter(self, endpoint: str, watermark: Any) -> None:
        # The first incremental run has no stored cursor, and a bad cursor converts to None. Either
        # way the filter must be dropped so the request backfills instead of asking for `__start=None`.
        _, wired, _, _ = _run(
            endpoint,
            [_response([{"id": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert not [key for key in wired.params[0] if key.endswith("__start")]

    @pytest.mark.parametrize("endpoint", sorted(BUTTONDOWN_ENDPOINTS))
    def test_ordering_param_matches_the_endpoint_config(self, endpoint: str) -> None:
        config = BUTTONDOWN_ENDPOINTS[endpoint]
        _, wired, _, _ = _run(endpoint, [_response([{"id": "a"}])])

        assert wired.params[0].get("ordering") == config.ordering

    @pytest.mark.parametrize(
        "endpoint",
        sorted(name for name, config in BUTTONDOWN_ENDPOINTS.items() if config.incremental_start_param),
    )
    def test_ascending_sort_mode_is_backed_by_an_explicit_ordering(self, endpoint: str) -> None:
        config = BUTTONDOWN_ENDPOINTS[endpoint]

        # An "asc" watermark is checkpointed after every batch, so it is only safe when the request
        # forces ascending order. Anything else must stay on the end-of-job commit path.
        assert config.sort_mode == "desc" or config.ordering == "creation_date"

    @pytest.mark.parametrize("endpoint", sorted(BUTTONDOWN_ENDPOINTS))
    def test_source_response_shape_per_endpoint(self, endpoint: str) -> None:
        config = BUTTONDOWN_ENDPOINTS[endpoint]
        _, _, response, _ = _run(endpoint, [_response([{"id": "a"}])])

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)

    def test_missing_results_key_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="matched nothing"):
            _run("subscribers", [_response(None, drop_results=True)])

    def test_empty_results_page_is_not_an_error(self) -> None:
        rows, _, _, _ = _run("subscribers", [_response([])])

        assert rows == []


class TestToStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 15, 30), "2026-03-03"),
            (date(2026, 3, 4), "2026-03-03"),
            ("2026-03-04T15:30:00Z", "2026-03-03"),
            ("2026-03-04", "2026-03-03"),
            ("2026-03-01", "2026-02-28"),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_formats_watermarks_as_dates(self, value: Any, expected: str | None) -> None:
        assert _to_start_date(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [(200, (True, 200)), (401, (False, 401)), (403, (False, 403)), (500, (False, 500))],
    )
    def test_maps_probe_status_to_result(self, status_code: int, expected: tuple[bool, int]) -> None:
        with mock.patch(BUTTONDOWN_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            assert validate_credentials("bd-key") == expected

    def test_transport_failure_is_not_validated(self) -> None:
        with mock.patch(BUTTONDOWN_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("bd-key") == (False, None)

    def test_probe_sends_token_prefixed_key(self) -> None:
        with mock.patch(BUTTONDOWN_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("bd-key")

        url = mock_session.return_value.get.call_args.args[0]
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert url == f"{BUTTONDOWN_BASE_URL}/accounts/me"
        assert headers["Authorization"] == "Token bd-key"
