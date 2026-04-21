import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The transport module lives alongside the vendored autoresearch scripts.
# Loading it via sys.path keeps that code shape intact without needing to
# re-export it through the Django backend package.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "autoresearch" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from transports import (  # noqa: E402
    PosthogProxyTransport,
    TransportError,
    load_transport,
)


class TestPosthogProxyTransport:
    def test_factory_requires_url(self):
        with pytest.raises(ValueError, match="url"):
            load_transport({"type": "posthog_proxy", "cluster": "test", "token": "t"})

    def test_factory_requires_cluster(self):
        with pytest.raises(ValueError, match="cluster"):
            load_transport({"type": "posthog_proxy", "url": "http://x", "token": "t"})

    def test_factory_rejects_bogus_cluster(self):
        with pytest.raises(ValueError, match="cluster"):
            load_transport({"type": "posthog_proxy", "url": "http://x", "cluster": "prodd", "token": "t"})

    def test_factory_requires_token(self):
        with pytest.raises(ValueError, match="token"):
            load_transport({"type": "posthog_proxy", "url": "http://x", "cluster": "test"})

    def test_run_posts_to_execute_test_with_bearer_and_unwraps_response(self):
        transport = PosthogProxyTransport(
            base_url="http://posthog.internal:8000",
            cluster="test",
            token="tok-123",
        )

        proxy_response = json.dumps(
            {
                "result": "1\n",
                "elapsed_ms": 42.5,
                "rows_read": 1,
                "bytes_read": 1,
                "query_id": "qid-abc",
            }
        ).encode("utf-8")

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = proxy_response
        with patch("transports.urllib.request.urlopen", return_value=mock_ctx) as mocked:
            result = transport.run("SELECT 1")

        called_req = mocked.call_args.args[0]
        assert called_req.full_url == "http://posthog.internal:8000/api/query_performance_proxy/execute-test/"
        assert called_req.get_method() == "POST"
        assert called_req.headers["Authorization"] == "Bearer tok-123"
        assert called_req.headers["Content-type"] == "application/json"
        assert json.loads(called_req.data) == {"sql": "SELECT 1"}

        assert result.result_bytes == b"1\n"
        assert result.elapsed_ms == pytest.approx(42.5)
        assert result.rows_read == 1
        assert result.bytes_read == 1
        assert "qid-abc" in result.stdout

    def test_run_targets_prod_cluster_url_when_configured(self):
        transport = PosthogProxyTransport(
            base_url="http://posthog.internal:8000/",  # trailing slash handled
            cluster="prod",
            token="tok-prod",
        )

        proxy_response = b'{"result": "", "elapsed_ms": 1.0, "rows_read": null, "bytes_read": null, "query_id": null}'
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = proxy_response
        with patch("transports.urllib.request.urlopen", return_value=mock_ctx) as mocked:
            transport.run("SELECT 1 WHERE team_id = 2")

        called_req = mocked.call_args.args[0]
        assert called_req.full_url == "http://posthog.internal:8000/api/query_performance_proxy/execute-prod/"

    def test_run_wraps_http_error_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", cluster="test", token="tok")

        import urllib.error

        err = urllib.error.HTTPError(
            url="http://x/api/query_performance_proxy/execute-test/",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        err.read = lambda: b'{"error":"sql must begin with a read-only statement"}'  # type: ignore[method-assign]

        with patch("transports.urllib.request.urlopen", side_effect=err):
            with pytest.raises(TransportError) as excinfo:
                transport.run("INSERT INTO t VALUES (1)")
        assert "400" in str(excinfo.value)
        assert "read-only" in str(excinfo.value)

    def test_run_wraps_url_error_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", cluster="test", token="tok")

        import urllib.error

        with patch("transports.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with pytest.raises(TransportError, match="refused"):
                transport.run("SELECT 1")

    def test_run_wraps_non_json_response_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", cluster="test", token="tok")

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = b"<html>oops</html>"
        with patch("transports.urllib.request.urlopen", return_value=mock_ctx):
            with pytest.raises(TransportError, match="non-JSON"):
                transport.run("SELECT 1")
