import sys
import json
import urllib.error
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

# transports.py is run inside the sandbox, not as a Django package import.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "autoresearch" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from transports import PosthogProxyTransport, TransportError, load_transport  # noqa: E402


class TestPosthogProxyTransport:
    def test_factory_requires_url(self):
        with pytest.raises(ValueError, match="url"):
            load_transport({"type": "posthog_proxy", "token": "t"})

    def test_factory_requires_token(self):
        with pytest.raises(ValueError, match="token"):
            load_transport({"type": "posthog_proxy", "url": "http://x"})

    def test_run_posts_to_execute_test_with_bearer_and_unwraps_response(self):
        transport = PosthogProxyTransport(
            base_url="http://posthog.internal:8000",
            token="tok-123",
        )

        proxy_response = json.dumps(
            {
                "result": [[1, "a"], [2, None]],
                "elapsed_ms": 42.5,
                "rows_read": 2,
                "bytes_read": 1,
                "rows_returned": 2,
                "query_id": "qid-deadbeef",
            }
        ).encode("utf-8")

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = proxy_response
        with patch("transports._NO_REDIRECT_OPENER.open", return_value=mock_ctx) as mocked:
            result = transport.run("SELECT 1")

        called_req = mocked.call_args.args[0]
        assert called_req.full_url == "http://posthog.internal:8000/api/query_performance_proxy/execute-test/"
        assert called_req.get_method() == "POST"
        assert called_req.headers["Authorization"] == "Bearer tok-123"
        assert called_req.headers["Content-type"] == "application/json"
        assert json.loads(called_req.data) == {"sql": "SELECT 1"}

        # JSON-lines so ch_compare_results.py's text diff keeps working.
        assert result.result_bytes == b'[1,"a"]\n[2,null]\n'
        assert result.elapsed_ms == pytest.approx(42.5)
        assert result.rows_read == 2
        assert result.bytes_read == 1
        assert result.query_id == "qid-deadbeef"
        assert "rows_returned=2" in result.stdout

    def test_run_strips_trailing_slash_from_base_url(self):
        transport = PosthogProxyTransport(
            base_url="http://posthog.internal:8000/",
            token="tok",
        )

        proxy_response = b'{"result": [], "elapsed_ms": 1.0, "rows_read": 0, "bytes_read": null, "rows_returned": 0}'
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = proxy_response
        with patch("transports._NO_REDIRECT_OPENER.open", return_value=mock_ctx) as mocked:
            transport.run("SELECT 1")

        called_req = mocked.call_args.args[0]
        assert called_req.full_url == "http://posthog.internal:8000/api/query_performance_proxy/execute-test/"

    def test_run_wraps_http_error_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", token="tok")
        err = urllib.error.HTTPError(
            url="http://x/api/query_performance_proxy/execute-test/",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        err.read = lambda: b'{"error":"sql must begin with a read-only statement"}'  # type: ignore[method-assign,misc,assignment] # ty: ignore[invalid-assignment]

        with patch("transports._NO_REDIRECT_OPENER.open", side_effect=err):
            with pytest.raises(TransportError) as excinfo:
                transport.run("INSERT INTO t VALUES (1)")
        assert "400" in str(excinfo.value)
        assert "read-only" in str(excinfo.value)

    def test_run_wraps_url_error_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", token="tok")
        with patch("transports._NO_REDIRECT_OPENER.open", side_effect=urllib.error.URLError("refused")):
            with pytest.raises(TransportError, match="refused"):
                transport.run("SELECT 1")

    def test_run_wraps_non_json_response_as_transport_error(self):
        transport = PosthogProxyTransport(base_url="http://x", token="tok")

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = b"<html>oops</html>"
        with patch("transports._NO_REDIRECT_OPENER.open", return_value=mock_ctx):
            with pytest.raises(TransportError, match="non-JSON"):
                transport.run("SELECT 1")
