import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe import (
    SecureframeResumeConfig,
    _extract_rows,
    get_endpoint_permissions,
    secureframe_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import (
    ENDPOINTS,
    SECUREFRAME_ENDPOINTS,
)

# The rest_source client builds/uses its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The source builds its own tracked session (for the transport session + probes) in the secureframe module.
SECUREFRAME_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe.make_tracked_session"
)


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: SecureframeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when
    each request is prepared instead of inspecting the (final) shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(session_factory_mock, responses, endpoint="controls", manager=None):
    session = session_factory_mock.return_value
    params = _wire(session, responses)
    manager = manager or _make_manager()
    source = secureframe_source(
        api_key="key",
        api_secret="secret",
        region="us",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )
    return _rows(source), params, session, manager


class TestExtractRows:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            # Array of per-item JSON:API envelopes (the shape the OpenAPI spec declares).
            (
                [{"data": {"id": "a", "type": "control", "attributes": {"name": "x"}}}],
                [{"id": "a", "name": "x"}],
            ),
            # Standard JSON:API document with a top-level data array.
            (
                {"data": [{"id": "b", "type": "control", "attributes": {"id": "b", "name": "y"}}]},
                [{"id": "b", "name": "y"}],
            ),
            # Plain row dicts, with and without a wrapping data key.
            ([{"id": "c", "name": "z"}], [{"id": "c", "name": "z"}]),
            ({"data": [{"id": "d", "name": "w"}]}, [{"id": "d", "name": "w"}]),
            # Attributes win, but a missing id is backfilled from the envelope.
            (
                [{"data": {"id": "e", "attributes": {"name": "v", "id": "other"}}}],
                [{"id": "other", "name": "v"}],
            ),
            # Unexpected payloads yield nothing instead of raising.
            ({"message": "Authorization failed"}, []),
            ([], []),
            (None, []),
            ("not json we expect", []),
            ([None, "junk", 42], []),
        ],
    )
    def test_extract_rows_shapes(self, payload, expected):
        assert _extract_rows(payload) == expected


class TestPagination:
    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_region_maps_to_host(self, MockSession):
        # base_url selects the host; unknown regions fall back to US.
        for region, expected_host in [
            ("us", "https://api.secureframe.com"),
            ("uk", "https://api-uk.secureframe.com"),
            ("unknown", "https://api.secureframe.com"),
        ]:
            session = MockSession.return_value
            sent: list[str] = []

            def _prepare(request, _sent=sent):
                _sent.append(request.url)
                return mock.MagicMock()

            session.prepare_request.side_effect = _prepare
            session.send.side_effect = [_response({"data": []})]

            source = secureframe_source(
                api_key="key",
                api_secret="secret",
                region=region,
                endpoint="controls",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
            _rows(source)
            assert sent[0].startswith(f"{expected_host}/controls")

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_paginates_until_empty_page(self, MockSession):
        rows, params, session, _ = _run(
            MockSession,
            [
                _response({"data": [{"id": "1", "attributes": {"id": "1"}}, {"id": "2", "attributes": {"id": "2"}}]}),
                _response({"data": [{"id": "3", "attributes": {"id": "3"}}]}),
                _response({"data": []}),
            ],
        )

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # First page is 1, then 2, then the empty terminating page 3, and per_page rides along.
        assert [p["page"] for p in params] == [1, 2, 3]
        assert all(p["per_page"] == 100 for p in params)
        assert session.send.call_count == 3

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_top_level_array_envelopes_are_flattened(self, MockSession):
        # The declared shape: a top-level array of per-item JSON:API envelopes.
        rows, _params, _session, _ = _run(
            MockSession,
            [
                _response([{"data": {"id": "a", "type": "control", "attributes": {"name": "x"}}}]),
                _response([]),
            ],
        )
        assert rows == [{"id": "a", "name": "x"}]

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_state_saved_after_each_yielded_batch(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"data": [{"id": "1", "attributes": {"id": "1"}}]}),
                _response({"data": []}),
            ],
        )

        manager = _make_manager()
        source = secureframe_source(
            api_key="key",
            api_secret="secret",
            region="us",
            endpoint="controls",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
        rows_iterator = iter(cast("Iterable[Any]", source.items()))

        next(rows_iterator)
        # Paused at the first yield: page 1 is in flight downstream, so no checkpoint yet —
        # a crash here must re-fetch page 1, not skip it.
        manager.save_state.assert_not_called()

        assert list(rows_iterator) == []
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SecureframeResumeConfig(page=2)

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        _rows_out, params, _session, _ = _run(
            MockSession,
            [_response({"data": []})],
            manager=_make_manager(SecureframeResumeConfig(page=5)),
        )
        assert params[0]["page"] == 5

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_auth_failure_raises_instead_of_ending_sync(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"message": "Authorization failed"}, status_code=401)])

        manager = _make_manager()
        source = secureframe_source(
            api_key="key",
            api_secret="secret",
            region="us",
            endpoint="controls",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
        with pytest.raises(HTTPError):
            _rows(source)

        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, True)),
            # A valid key whose role lacks the probed scope is authenticated but not authorized.
            (403, (True, False)),
            (401, (False, False)),
            (500, (False, False)),
        ],
    )
    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key", "secret", "us") == expected

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret", "us") == (False, False)

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_probes_requested_endpoint(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("key", "secret", "us", endpoint="devices")

        assert "/devices?" in mock_session.return_value.get.call_args.args[0]


class TestGetEndpointPermissions:
    @pytest.mark.parametrize("denied_status", [401, 403])
    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_denied_endpoints_carry_a_reason(self, mock_session, denied_status):
        ok = mock.MagicMock(status_code=200)
        denied = mock.MagicMock(status_code=denied_status)
        mock_session.return_value.get.side_effect = [ok, denied]

        permissions = get_endpoint_permissions("key", "secret", "us", ["controls", "tests"])

        assert permissions["controls"] is None
        assert permissions["tests"] is not None
        assert "tests" in permissions["tests"]

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_transient_failures_are_not_denials(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("connection reset")

        assert get_endpoint_permissions("key", "secret", "us", ["controls"]) == {"controls": None}


class TestSessionHardening:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: validate_credentials("key", "secret", "us"),
            lambda: get_endpoint_permissions("key", "secret", "us", ["controls"]),
        ],
    )
    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_session_excludes_responses_from_sample_capture_and_redacts_credentials(self, mock_session, call):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        call()

        # Secureframe responses carry customer PII the generic scrubber can't remove, so the
        # session must opt out of HTTP sample capture and mask both credential halves.
        _, kwargs = mock_session.call_args
        assert kwargs["capture"] is False
        assert set(kwargs["redact_values"]) == {"key", "secret"}

    @mock.patch(SECUREFRAME_SESSION_PATCH)
    def test_sync_transport_session_is_hardened(self, mock_session):
        # The transport session handed to the rest_source client is built the same way.
        session = mock_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock()
        session.send.side_effect = [_response({"data": []})]

        source = secureframe_source(
            api_key="key",
            api_secret="secret",
            region="us",
            endpoint="controls",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        _rows(source)

        _, kwargs = mock_session.call_args
        assert kwargs["capture"] is False
        assert set(kwargs["redact_values"]) == {"key", "secret"}
        assert kwargs["headers"]["Authorization"] == "key secret"


class TestSecureframeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SECUREFRAME_ENDPOINTS[endpoint]
        response = secureframe_source(
            api_key="key",
            api_secret="secret",
            region="us",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SECUREFRAME_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
