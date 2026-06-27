from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.metabase import metabase as metabase_module
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import (
    API_KEY_AUTH,
    SESSION_AUTH,
    MetabaseAuth,
    MetabaseAuthError,
    MetabaseHostNotAllowedError,
    _extract_items,
    _redact_values_for_data_requests,
    _resolve_auth_headers,
    get_rows,
    metabase_source,
    normalize_host,
    validate_credentials,
)


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    return response


def _api_key_auth() -> MetabaseAuth:
    return MetabaseAuth(method=API_KEY_AUTH, api_key="mb_secret")


def _session_auth() -> MetabaseAuth:
    return MetabaseAuth(method=SESSION_AUTH, username="me@example.com", password="hunter2")


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("https://company.metabaseapp.com/", "https://company.metabaseapp.com"),
            ("https://company.metabaseapp.com/api", "https://company.metabaseapp.com"),
            ("  company.metabaseapp.com  ", "https://company.metabaseapp.com"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
            # Plaintext HTTP to a remote host is upgraded to HTTPS so credentials aren't sent in the clear.
            ("http://company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("HTTP://company.metabaseapp.com/api", "https://company.metabaseapp.com"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestExtractItems:
    @pytest.mark.parametrize(
        "data, expected",
        [
            ([{"id": 1}, {"id": 2}], [{"id": 1}, {"id": 2}]),
            ({"data": [{"id": 1}], "total": 1}, [{"id": 1}]),
            ({"total": 0}, []),
            (None, []),
            ("nonsense", []),
            ([{"id": 1}, "skip-me", 5], [{"id": 1}]),
        ],
    )
    def test_extract_items(self, data, expected):
        assert _extract_items(data) == expected


class TestResolveAuthHeaders:
    def _patch_mint(self, post_response=None):
        session = mock.MagicMock()
        session.post.return_value = post_response
        return session, mock.patch.object(metabase_module, "make_tracked_session", return_value=session)

    def test_api_key_header(self):
        session, patch = self._patch_mint()
        with patch:
            headers = _resolve_auth_headers("https://x.metabaseapp.com", _api_key_auth(), mock.MagicMock())
        assert headers["x-api-key"] == "mb_secret"
        # API-key auth makes no network call to mint anything.
        session.post.assert_not_called()

    def test_api_key_missing_raises(self):
        auth = MetabaseAuth(method=API_KEY_AUTH, api_key=None)
        with pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", auth, mock.MagicMock())

    def test_session_mints_token(self):
        session, patch = self._patch_mint(_response(json_data={"id": "session-token-abc"}))
        with patch as patched:
            headers = _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())
        assert headers["X-Metabase-Session"] == "session-token-abc"
        # The token is exchanged at the session endpoint, never persisted.
        assert session.post.call_args.args[0] == "https://x.metabaseapp.com/api/session"
        assert session.post.call_args.kwargs["allow_redirects"] is False
        # The mint exchange is excluded from HTTP sample capture so neither the password
        # (request body) nor the minted token (response `id`) can land in a captured sample.
        assert patched.call_args.kwargs["capture"] is False

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    def test_session_bad_credentials_raises_auth_error(self, status_code):
        session, patch = self._patch_mint(_response(status_code=status_code))
        with patch, pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())

    def test_session_missing_username_raises(self):
        auth = MetabaseAuth(method=SESSION_AUTH, username=None, password="x")
        with pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", auth, mock.MagicMock())

    def test_session_no_token_in_response_raises(self):
        session, patch = self._patch_mint(_response(json_data={}))
        with patch, pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())

    @pytest.mark.parametrize("status_code", [404, 422, 500])
    def test_session_unexpected_status_raises_retryable_not_httperror(self, status_code):
        # Unexpected non-auth statuses must surface as a typed retryable error so callers'
        # except clauses catch them, not a raw requests HTTPError.
        session, patch = self._patch_mint(_response(status_code=status_code))
        with patch, pytest.raises(metabase_module.MetabaseRetryableError):
            _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())


class TestRedactValuesForDataRequests:
    def test_api_key(self):
        assert _redact_values_for_data_requests(_api_key_auth(), {}) == ("mb_secret",)

    def test_session_includes_creds_and_minted_token(self):
        values = _redact_values_for_data_requests(_session_auth(), {"X-Metabase-Session": "tok-123"})
        assert set(values) == {"me@example.com", "hunter2", "tok-123"}


class TestValidateCredentials:
    def _patch_session(self, get_response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = get_response
        return mock.patch.object(metabase_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials("https://x.metabaseapp.com", _api_key_auth()) == (True, None)

    def test_invalid_credentials(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg == "Invalid Metabase credentials"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials("https://x.metabaseapp.com", _api_key_auth(), schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth(), schema_name="cards")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_host", ["", "https://", "not a host!"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, _api_key_auth())
        assert valid is False
        assert msg == "Invalid Metabase host"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg == metabase_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(metabase_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", _api_key_auth(), team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_bad_session_credentials_surface_before_probe(self):
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=401)
        with mock.patch.object(metabase_module, "make_tracked_session", return_value=session):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _session_auth())
            assert valid is False
            assert msg == "Invalid Metabase username or password"
            session.get.assert_not_called()

    def test_unexpected_session_status_returns_failure_not_raises(self):
        # A 404 (e.g. wrong API path) during session minting must come back as (False, msg), not an
        # uncaught HTTPError bubbling out of source creation.
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=404)
        with mock.patch.object(metabase_module, "make_tracked_session", return_value=session):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _session_auth())
            assert valid is False
            assert msg is not None
            session.get.assert_not_called()

    def test_unexpected_status_does_not_leak_response_body(self):
        # When the host isn't a Metabase instance it returns an arbitrary body (e.g. a hosting
        # provider's error page). That body must never reach the user — only a friendly,
        # status-coded message that points them back at the Instance URL.
        leaked_body = '{"error": {"code": "404", "message": "SENTINEL_UPSTREAM_BODY"}}'
        with self._patch_session(_response(status_code=404, json_data={"error": {"code": "404"}}, text=leaked_body)):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg is not None
            assert "SENTINEL_UPSTREAM_BODY" not in msg
            assert "404" in msg


class TestMetabaseSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("cards", ["id"], "created_at"),
            ("dashboards", ["id"], "created_at"),
            ("databases", ["id"], "created_at"),
            ("native_query_snippets", ["id"], "created_at"),
            ("users", ["id"], "date_joined"),
            ("collections", ["id"], None),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = metabase_source(
            host="https://x.metabaseapp.com",
            auth=_api_key_auth(),
            endpoint=endpoint,
            logger=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(self, responses: list[Any], auth: Optional[MetabaseAuth] = None, endpoint: str = "cards"):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(metabase_module, "make_tracked_session", return_value=session):
            rows: list[Any] = []
            for table in get_rows(
                host="https://x.metabaseapp.com",
                auth=auth or _api_key_auth(),
                endpoint=endpoint,
                logger=mock.MagicMock(),
                team_id=1,
            ):
                rows.extend(table)
        return rows, session

    def test_yields_bare_array(self):
        rows, session = self._run([_response(json_data=[{"id": 1}, {"id": 2}])])
        assert [r["id"] for r in rows] == [1, 2]
        assert session.get.call_count == 1
        assert session.get.call_args.args[0] == "https://x.metabaseapp.com/api/card"

    def test_yields_wrapped_array(self):
        rows, _ = self._run([_response(json_data={"data": [{"id": 7}], "total": 1})], endpoint="databases")
        assert [r["id"] for r in rows] == [7]

    def test_empty_collection_yields_nothing(self):
        rows, _ = self._run([_response(json_data=[])])
        assert rows == []

    def test_passes_allow_redirects_false(self):
        _rows, session = self._run([_response(json_data=[{"id": 1}])])
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_rejects_redirect(self):
        with pytest.raises(MetabaseHostNotAllowedError):
            self._run([_response(status_code=302)])

    def test_blocks_unsafe_host_at_runtime(self):
        with mock.patch.object(metabase_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(MetabaseHostNotAllowedError):
                self._run([_response(json_data=[{"id": 1}])])

    def test_session_auth_mints_token_then_lists(self):
        session = mock.MagicMock()
        session.post.return_value = _response(json_data={"id": "tok-123"})
        session.get.return_value = _response(json_data=[{"id": 1}])
        with mock.patch.object(metabase_module, "make_tracked_session", return_value=session):
            rows = list(
                get_rows(
                    host="https://x.metabaseapp.com",
                    auth=_session_auth(),
                    endpoint="cards",
                    logger=mock.MagicMock(),
                    team_id=1,
                )
            )
        assert session.post.called
        assert session.get.call_args.kwargs["headers"]["X-Metabase-Session"] == "tok-123"
        assert [r["id"] for batch in rows for r in batch] == [1]
