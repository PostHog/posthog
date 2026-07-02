import ipaddress

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze import (
    PgAnalyzeRetryableError,
    _post_graphql,
    _resolve_api_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.settings import PGANALYZE_API_URL

_PUBLIC_IP = {ipaddress.ip_address("93.184.216.34")}


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.reason = "OK" if response.ok else "Error"
    response.text = text
    if json_data is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_data
    return response


class TestPostGraphql:
    def test_returns_data_on_success(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"data": {"getServers": []}})

        result = _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

        assert result == {"getServers": []}

    def test_raises_retryable_on_5xx(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=502, text="bad gateway")

        with pytest.raises(PgAnalyzeRetryableError, match="server error 502"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_retryable_on_429(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=429, text="too many")

        with pytest.raises(PgAnalyzeRetryableError, match="rate limited"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_graphql_errors_field(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"errors": [{"message": "field x not found"}]})

        with pytest.raises(Exception, match="GraphQL error"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_missing_data_key(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"unexpected": "shape"})

        with pytest.raises(Exception, match="Unexpected pganalyze response format"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})


class TestValidateCredentials:
    def test_returns_true_on_valid_credentials(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session"
        ) as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(json_data={"data": {"getServers": []}})
            mock_sess.return_value = sess

            ok, err = validate_credentials("token", "acme", None)

            assert ok is True
            assert err is None
            sess.post.assert_called_once()
            sess.close.assert_called_once()

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_returns_false_on_auth_error(self, status_code):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session"
        ) as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(status_code=status_code, text="forbidden")
            mock_sess.return_value = sess

            ok, err = validate_credentials("bad", "acme", None)

            assert ok is False
            assert err is not None
            assert "Invalid" in err

    def test_returns_false_on_graphql_error(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session"
        ) as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(json_data={"errors": [{"message": "Organization not found"}]})
            mock_sess.return_value = sess

            ok, err = validate_credentials("token", "wrong-slug", None)

            assert ok is False
            assert err is not None
            assert "Organization not found" in err

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/",
            "http://127.0.0.1/graphql",
            "http://localhost/graphql",
            "http://10.0.0.1/graphql",
            "file:///etc/passwd",
        ],
    )
    def test_returns_false_for_ssrf_targets(self, blocked_url):
        # is_url_allowed short-circuits in dev mode (DEBUG=True), so force it off
        with mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            ok, err = validate_credentials("token", "acme", blocked_url)

        assert ok is False
        assert err is not None
        assert "not allowed" in err


class TestResolveApiUrl:
    def test_defaults_to_public_api_when_none(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            assert _resolve_api_url(None) == PGANALYZE_API_URL

    def test_defaults_to_public_api_when_empty_string(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            assert _resolve_api_url("") == PGANALYZE_API_URL
            assert _resolve_api_url("   ") == PGANALYZE_API_URL

    def test_accepts_well_formed_public_url(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            url = "https://app.pganalyze.com/graphql"
            assert _resolve_api_url(url) == url

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/graphql",
            "http://localhost/graphql",
        ],
    )
    def test_rejects_ssrf_targets(self, blocked_url):
        with mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                _resolve_api_url(blocked_url)
