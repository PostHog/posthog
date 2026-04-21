import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests

from products.tasks.backend.services.agent_command import (
    REFRESH_SESSION_METHOD,
    REFRESH_TIMEOUT_SECONDS,
    CommandResult,
    _build_request_args,
    send_agent_command,
    send_cancel,
    send_refresh_session,
    send_user_message,
    validate_sandbox_url,
)


class TestValidateSandboxUrl:
    @pytest.mark.parametrize(
        "url,expected_error",
        [
            ("https://sandbox.modal.run/rpc", None),
            ("https://some-host.example.com:8080/api", None),
            ("http://sandbox.modal.run/rpc", "Scheme 'http' not allowed"),
            ("ftp://sandbox.modal.run/rpc", "Scheme 'ftp' not allowed"),
            ("", "Scheme '' not allowed"),
            ("https://", "No hostname in URL"),
        ],
        ids=[
            "valid_https",
            "valid_https_with_port",
            "rejected_http",
            "rejected_ftp",
            "rejected_empty",
            "rejected_no_host",
        ],
    )
    def test_scheme_and_host_validation(self, url: str, expected_error: str | None):
        if expected_error is None:
            # We can't fully validate without DNS, but scheme+host parsing should pass
            result = validate_sandbox_url(url)
            # May fail on DNS but won't fail on scheme/host
            assert result is None or "Cannot resolve" in result
        else:
            result = validate_sandbox_url(url)
            assert result is not None
            assert expected_error in result

    @pytest.mark.parametrize(
        "hostname",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
        ],
        ids=["loopback", "class_a_private", "class_b_private", "class_c_private"],
    )
    @patch("products.tasks.backend.services.agent_command.socket.getaddrinfo")
    def test_ssrf_blocked_private_ips(self, mock_getaddrinfo, hostname):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", (hostname, 443)),
        ]
        result = validate_sandbox_url(f"https://{hostname}/rpc")
        assert result is not None
        assert "blocked range" in result

    @patch("products.tasks.backend.services.agent_command.socket.getaddrinfo")
    def test_ssrf_allows_public_ip(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("52.1.2.3", 443)),
        ]
        result = validate_sandbox_url("https://public-host.example.com/rpc")
        assert result is None

    @override_settings(DEBUG=True)
    @patch("products.tasks.backend.services.agent_command.socket.getaddrinfo")
    def test_localhost_http_allowed_in_debug(self, mock_getaddrinfo):
        result = validate_sandbox_url("http://localhost:1234/command")
        assert result is None
        mock_getaddrinfo.assert_not_called()

    @override_settings(DEBUG=True)
    @patch("products.tasks.backend.services.agent_command.socket.getaddrinfo")
    def test_loopback_http_allowed_in_debug(self, mock_getaddrinfo):
        result = validate_sandbox_url("http://127.0.0.1:1234/command")
        assert result is None
        mock_getaddrinfo.assert_not_called()

    @override_settings(DEBUG=True)
    def test_non_local_http_still_blocked_in_debug(self):
        result = validate_sandbox_url("http://sandbox.modal.run/rpc")
        assert result is not None
        assert "Scheme 'http' not allowed" in result

    @override_settings(DEBUG=False)
    def test_localhost_http_blocked_outside_debug(self):
        result = validate_sandbox_url("http://localhost:1234/command")
        assert result is not None
        assert "Scheme 'http' not allowed" in result


class TestBuildRequestArgs:
    @pytest.mark.parametrize(
        "connect_token,auth_token,expected_auth,expected_query_param",
        [
            ("modal-tok", "jwt-tok", "Bearer jwt-tok", "modal-tok"),
            ("modal-tok", None, "Bearer modal-tok", None),
            (None, "jwt-tok", "Bearer jwt-tok", None),
            (None, None, None, None),
        ],
        ids=[
            "jwt_with_modal_tunnel",
            "single_header_internal_caller",
            "jwt_only_no_modal",
            "no_tokens",
        ],
    )
    def test_auth_scheme(self, connect_token, auth_token, expected_auth, expected_query_param):
        headers, query_params = _build_request_args(connect_token, auth_token)
        assert headers.get("Authorization") == expected_auth
        assert query_params.get("_modal_connect_token") == expected_query_param
        assert headers["Content-Type"] == "application/json"


class TestSendAgentCommand:
    def _make_task_run(self, sandbox_url: str | None = None, connect_token: str | None = None):
        run = MagicMock()
        run.id = "test-run-id"
        run.state = {}
        if sandbox_url:
            run.state["sandbox_url"] = sandbox_url
        if connect_token:
            run.state["sandbox_connect_token"] = connect_token
        return run

    def test_no_sandbox_url(self):
        task_run = self._make_task_run()
        result = send_agent_command(task_run, "test_method")
        assert not result.success
        assert result.error == "No sandbox URL available"
        assert not result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url")
    def test_ssrf_blocked(self, mock_validate):
        mock_validate.return_value = "Address 127.0.0.1 is in blocked range"
        task_run = self._make_task_run(sandbox_url="https://evil.local/rpc")
        result = send_agent_command(task_run, "test_method")
        assert not result.success
        error = result.error or ""
        assert "validation failed" in error
        assert not result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_success(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "ok"}
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc", connect_token="tok")
        result = send_agent_command(task_run, "user_message", params={"message": "hi"})

        assert result.success
        assert result.status_code == 200
        assert result.data == {"jsonrpc": "2.0", "result": "ok"}

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert call_kwargs.kwargs["json"]["method"] == "user_message"
        assert call_kwargs.args[0] == "https://sandbox.modal.run/rpc/command"

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_appends_command_path_when_missing_trailing_slash(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "ok"}
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="http://localhost:6001", connect_token=None)
        result = send_agent_command(task_run, "user_message", params={"content": "hi"})

        assert result.success
        assert mock_post.call_args.args[0] == "http://localhost:6001/command"

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_tunnel_auth_with_auth_token(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jsonrpc": "2.0", "result": "ok"}
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc", connect_token="modal-tok")
        result = send_agent_command(task_run, "user_message", params={"message": "hi"}, auth_token="jwt-tok")

        assert result.success
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer jwt-tok"
        assert call_kwargs.kwargs["params"] == {"_modal_connect_token": "modal-tok"}

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_connection_error_is_retryable(self, mock_post, mock_validate):
        mock_post.side_effect = requests.ConnectionError("refused")
        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc")
        result = send_agent_command(task_run, "cancel")
        assert not result.success
        assert result.status_code == 502
        assert result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_timeout_is_retryable(self, mock_post, mock_validate):
        mock_post.side_effect = requests.Timeout("timed out")
        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc")
        result = send_agent_command(task_run, "cancel")
        assert not result.success
        assert result.status_code == 504
        assert result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_5xx_is_retryable(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc")
        result = send_agent_command(task_run, "cancel")
        assert not result.success
        assert result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_4xx_is_not_retryable(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc")
        result = send_agent_command(task_run, "cancel")
        assert not result.success
        assert not result.retryable

    @patch("products.tasks.backend.services.agent_command.validate_sandbox_url", return_value=None)
    @patch("products.tasks.backend.services.agent_command.requests.post")
    def test_jsonrpc_error_in_200_response_is_detected(self, mock_post, mock_validate):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32603, "message": "Output blocked by content filtering policy"},
        }
        mock_post.return_value = mock_resp

        task_run = self._make_task_run(sandbox_url="https://sandbox.modal.run/rpc")
        result = send_agent_command(task_run, "user_message", params={"content": "hi"})
        assert not result.success
        assert "content filtering" in (result.error or "")
        assert not result.retryable


class TestSendUserMessage:
    @patch("products.tasks.backend.services.agent_command.send_agent_command")
    def test_sends_user_message_method(self, mock_send):
        mock_send.return_value = CommandResult(success=True, status_code=200)
        task_run = MagicMock()
        result = send_user_message(task_run, "hello world")
        mock_send.assert_called_once_with(
            task_run,
            method="user_message",
            params={"content": "hello world"},
            auth_token=None,
            timeout=15,
        )
        assert result.success


class TestSendCancel:
    @patch("products.tasks.backend.services.agent_command.send_agent_command")
    def test_sends_cancel_method(self, mock_send):
        mock_send.return_value = CommandResult(success=True, status_code=200)
        task_run = MagicMock()
        result = send_cancel(task_run)
        mock_send.assert_called_once_with(
            task_run,
            method="cancel",
            timeout=10,
            auth_token=None,
        )
        assert result.success


class TestSendRefreshSession:
    @patch("products.tasks.backend.services.agent_command.send_agent_command")
    def test_sends_refresh_session_method(self, mock_send):
        mock_send.return_value = CommandResult(success=True, status_code=200, data={"result": {"refreshed": True}})
        task_run = MagicMock()
        mcp_servers = [
            {
                "type": "http",
                "name": "posthog",
                "url": "https://mcp.posthog.com/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer tok"}],
            }
        ]
        result = send_refresh_session(task_run, mcp_servers, auth_token="jwt")
        mock_send.assert_called_once_with(
            task_run,
            method=REFRESH_SESSION_METHOD,
            params={"mcpServers": mcp_servers},
            auth_token="jwt",
            timeout=REFRESH_TIMEOUT_SECONDS,
        )
        assert result.success
        assert REFRESH_SESSION_METHOD == "_posthog/refresh_session"
