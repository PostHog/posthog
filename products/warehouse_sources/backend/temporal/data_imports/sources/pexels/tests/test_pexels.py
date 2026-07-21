import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_client
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels import pexels
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels import (
    PexelsResumeConfig,
    _build_url,
    _get_headers,
    pexels_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the pexels module.
PEXELS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, data_key: str = "photos", next_page: str | None = None
) -> Response:
    body: dict[str, Any] = {data_key: items if items is not None else []}
    if next_page:
        body["next_page"] = next_page
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.pexels.com/v1/curated"
    return resp


def _status_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps({"error": "boom"}).encode()
    resp.url = "https://api.pexels.com/v1/curated"
    return resp


def _make_manager(resume_state: PexelsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://api.pexels.com/v1/curated"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBuildUrl:
    @parameterized.expand(
        [
            ("encodes_spaces", "https://api.pexels.com/v1/search", {"query": "red car"}, "query=red+car"),
            ("no_params", "https://api.pexels.com/v1/curated", {}, None),
            ("page_param", "https://api.pexels.com/v1/curated", {"per_page": 80, "page": 2}, "per_page=80&page=2"),
        ]
    )
    def test_build_url(self, _name: str, base: str, params: dict, expected_fragment: str | None) -> None:
        url = _build_url(base, params)
        if expected_fragment is None:
            assert url == base
        else:
            assert expected_fragment in url


class TestHeaders:
    def test_authorization_header_is_raw_key_without_bearer_prefix(self) -> None:
        # Pexels rejects a "Bearer " prefix — the key must be the raw Authorization value.
        headers = _get_headers("my-secret-key")
        assert headers["Authorization"] == "my-secret-key"
        assert "Bearer" not in headers["Authorization"]


class TestAuth:
    def test_request_sends_raw_key_as_authorization_without_bearer(self) -> None:
        # The framework api_key auth must put the raw key on Authorization (no "Bearer " prefix);
        # exercise a real prepare_request so the auth is actually applied.
        real_session = requests.Session()
        captured: dict[str, str | None] = {}

        def fake_send(prepared: Any, **_kwargs: Any) -> Response:
            captured["auth"] = prepared.headers.get("Authorization")
            return _response([])

        real_session.send = fake_send  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        with mock.patch(CLIENT_SESSION_PATCH, return_value=real_session):
            _rows(
                pexels_source(
                    api_key="raw-key",
                    endpoint="curated_photos",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )
        assert captured["auth"] == "raw-key"
        assert "Bearer" not in (captured["auth"] or "")


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_across_pages_until_empty(self, MockSession) -> None:
        session = MockSession.return_value
        # Two populated pages, then an empty page ends pagination (Pexels has no total-pages field).
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], next_page="https://api.pexels.com/v1/curated?page=2&per_page=80"),
                _response([{"id": 3}]),
                _response([]),
            ],
        )

        rows = _rows(
            pexels_source(
                api_key="k", endpoint="curated_photos", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 80
        assert params[1]["page"] == 2
        assert params[2]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_in_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        rows = _rows(
            pexels_source(
                api_key="k", endpoint="curated_photos", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_videos_data_key(self, MockSession) -> None:
        session = MockSession.return_value
        # popular_videos selects the "videos" key, not "photos".
        _wire(session, [_response([{"id": 9}], data_key="videos"), _response([], data_key="videos")])

        rows = _rows(
            pexels_source(
                api_key="k", endpoint="popular_videos", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == [{"id": 9}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_search_endpoint_sends_query_param(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}]), _response([])])

        _rows(
            pexels_source(
                api_key="k",
                endpoint="search_photos",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                search_query="red car",
            )
        )

        assert params[0]["query"] == "red car"

    @parameterized.expand([("none", None), ("empty", "")])
    def test_search_endpoint_without_query_raises(self, _name: str, query: str | None) -> None:
        # A missing query on a search endpoint must fail loudly, not send a literal `?query=None`.
        with pytest.raises(ValueError, match="requires a search query"):
            pexels_source(
                api_key="k",
                endpoint="search_photos",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                search_query=query,
            )


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_each_yield(self, MockSession) -> None:
        # State points at the NEXT page to fetch after each yielded page; the terminating empty page
        # saves nothing so a resume never starts past real data.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], next_page="https://api.pexels.com/v1/curated?page=2&per_page=80"),
                _response([{"id": 2}]),
                _response([]),
            ],
        )

        manager = _make_manager()
        _rows(
            pexels_source(
                api_key="k", endpoint="curated_photos", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [PexelsResumeConfig(page=2), PexelsResumeConfig(page=3)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        # A resumed job must start at the saved page, not page 1.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 2}]), _response([])])

        manager = _make_manager(PexelsResumeConfig(page=2))
        rows = _rows(
            pexels_source(
                api_key="k", endpoint="curated_photos", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert rows == [{"id": 2}]
        assert params[0]["page"] == 2


class TestRetryClassification:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_5xx_is_retried(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_status_response(500), _response([{"id": 1}]), _response([])])

        with mock.patch.object(rest_client.RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            rows = _rows(
                pexels_source(
                    api_key="k",
                    endpoint="curated_photos",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )

        assert rows == [{"id": 1}]
        # 500 retried, then the populated page, then the terminating empty page.
        assert session.send.call_count == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unauthorized_raises_and_is_not_retried(self, MockSession) -> None:
        # A 401 is a credential problem — it must surface immediately, not retry.
        session = MockSession.return_value
        _wire(session, [_status_response(401)])

        with pytest.raises(requests.HTTPError):
            _rows(
                pexels_source(
                    api_key="k",
                    endpoint="curated_photos",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )
        assert session.send.call_count == 1


class TestApiKeyRedaction:
    # Pexels sends the key as a raw Authorization value the sampler can't scrub by name, so the
    # source must register it for redaction (via the framework auth's secret_values) or the plaintext
    # key leaks into captured samples.
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_registers_api_key_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        _rows(
            pexels_source(
                api_key="secret-key",
                endpoint="curated_photos",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)

    def test_validate_credentials_registers_api_key_for_redaction(self) -> None:
        factory = mock.MagicMock()
        factory.return_value.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(PEXELS_SESSION_PATCH, factory):
            validate_credentials("secret-key")
        assert factory.call_args.kwargs["redact_values"] == ("secret-key",)


class TestPexelsSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_is_full_refresh_with_id_primary_key(self, MockSession) -> None:
        # Every endpoint keys on the global `id` and declares no datetime partition — Pexels has no
        # stable timestamp, so a partition key would rewrite partitions every sync.
        session = MockSession.return_value
        _wire(session, [_response([])])

        response = pexels_source(
            api_key="k", endpoint="curated_photos", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == "curated_photos"
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch.object(pexels, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_network_error_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(pexels, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is False
