from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Organization, Team

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion


def _create_running_app(team, user) -> tuple[StreamlitApp, StreamlitAppSandbox]:
    app = StreamlitApp.objects.create(team=team, name="Test App", created_by=user)
    version = StreamlitAppVersion.objects.create(
        app=app, version_number=1, zip_file="test.zip", zip_hash="abc", created_by=user
    )
    app.active_version = version
    app.save(update_fields=["active_version"])
    sandbox = StreamlitAppSandbox.objects.create(
        app=app,
        version=version,
        sandbox_id="modal-123",
        status=StreamlitAppSandbox.Status.RUNNING,
        current_viewers=0,
        max_viewers=20,
    )
    return app, sandbox


class TestStreamlitProxyAuth(APIBaseTest):
    def _proxy_url(self, short_id: str, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/streamlit_apps/{short_id}/proxy/{path}"

    def test_unauthenticated_request_returns_401(self):
        app, _sandbox = _create_running_app(self.team, self.user)
        self.client.logout()
        response = self.client.get(self._proxy_url(app.short_id))
        assert response.status_code == 401

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_authenticated_request_proxies(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok_abc"
        mock_runtime_cls.return_value = mock_runtime

        app, _sandbox = _create_running_app(self.team, self.user)

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"<html>streamlit</html>"
            mock_resp.headers = {"content-type": "text/html"}
            mock_req.return_value = mock_resp

            response = self.client.get(self._proxy_url(app.short_id, ""))
            assert response.status_code == 200
            assert response.content == b"<html>streamlit</html>"

    def test_wrong_team_returns_403(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        app, _sandbox = _create_running_app(other_team, self.user)

        response = self.client.get(self._proxy_url(app.short_id))
        # team_id in URL is our team, but app belongs to other_team
        assert response.status_code == 404

    def test_nonexistent_app_returns_404(self):
        response = self.client.get(self._proxy_url("nonexistent"))
        assert response.status_code == 404

    def test_deleted_app_returns_404(self):
        app, _sandbox = _create_running_app(self.team, self.user)
        app.deleted = True
        app.save(update_fields=["deleted"])
        response = self.client.get(self._proxy_url(app.short_id))
        assert response.status_code == 404


class TestStreamlitProxySandboxState(APIBaseTest):
    def _proxy_url(self, short_id: str, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/streamlit_apps/{short_id}/proxy/{path}"

    @parameterized.expand(
        [
            ("no_sandbox",),
            ("stopped",),
            ("starting",),
            ("error",),
        ]
    )
    def test_non_running_sandbox_returns_503(self, scenario):
        app = StreamlitApp.objects.create(team=self.team, name="Test App", created_by=self.user)
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="test.zip", zip_hash="abc")
        app.active_version = version
        app.save(update_fields=["active_version"])

        if scenario != "no_sandbox":
            status_map = {
                "stopped": StreamlitAppSandbox.Status.STOPPED,
                "starting": StreamlitAppSandbox.Status.STARTING,
                "error": StreamlitAppSandbox.Status.ERROR,
            }
            StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="sb", status=status_map[scenario])

        response = self.client.get(self._proxy_url(app.short_id))
        assert response.status_code == 503


class TestStreamlitProxyConcurrentViewers(APIBaseTest):
    def _proxy_url(self, short_id: str, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/streamlit_apps/{short_id}/proxy/{path}"

    def test_at_max_viewers_returns_503(self):
        app, sandbox = _create_running_app(self.team, self.user)
        sandbox.current_viewers = 20
        sandbox.max_viewers = 20
        sandbox.save(update_fields=["current_viewers", "max_viewers"])

        response = self.client.get(self._proxy_url(app.short_id))
        assert response.status_code == 503
        assert b"busy" in response.content.lower()

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_below_max_viewers_proxies(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok"
        mock_runtime_cls.return_value = mock_runtime

        app, sandbox = _create_running_app(self.team, self.user)
        sandbox.current_viewers = 19
        sandbox.max_viewers = 20
        sandbox.save(update_fields=["current_viewers", "max_viewers"])

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"ok"
            mock_resp.headers = {}
            mock_req.return_value = mock_resp

            response = self.client.get(self._proxy_url(app.short_id))
            assert response.status_code == 200


class TestStreamlitProxyActivityTracking(APIBaseTest):
    def _proxy_url(self, short_id: str, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/streamlit_apps/{short_id}/proxy/{path}"

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_proxy_updates_last_activity(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok"
        mock_runtime_cls.return_value = mock_runtime

        app, sandbox = _create_running_app(self.team, self.user)
        assert sandbox.last_activity_at is None

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"ok"
            mock_resp.headers = {}
            mock_req.return_value = mock_resp

            self.client.get(self._proxy_url(app.short_id))

        sandbox.refresh_from_db()
        assert sandbox.last_activity_at is not None


class TestStreamlitProxyForwarding(APIBaseTest):
    def _proxy_url(self, short_id: str, path: str = "") -> str:
        return f"/api/projects/{self.team.id}/streamlit_apps/{short_id}/proxy/{path}"

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_forwards_path_to_tunnel(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok_abc"
        mock_runtime_cls.return_value = mock_runtime

        app, _sandbox = _create_running_app(self.team, self.user)

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b""
            mock_resp.headers = {}
            mock_req.return_value = mock_resp

            self.client.get(self._proxy_url(app.short_id, "_stcore/stream"))

            call_kwargs = mock_req.call_args
            assert call_kwargs.kwargs["url"] == "https://tunnel.modal.host/_stcore/stream"
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer tok_abc"

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_no_tunnel_url_returns_502(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = None
        mock_runtime_cls.return_value = mock_runtime

        app, _sandbox = _create_running_app(self.team, self.user)

        response = self.client.get(self._proxy_url(app.short_id))
        assert response.status_code == 502

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_upstream_timeout_returns_504(self, mock_runtime_cls):
        import requests as real_requests

        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok"
        mock_runtime_cls.return_value = mock_runtime

        app, _sandbox = _create_running_app(self.team, self.user)

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_req.side_effect = real_requests.Timeout()

            response = self.client.get(self._proxy_url(app.short_id))
            assert response.status_code == 504

    @patch("products.streamlit_apps.backend.api.proxy.AppRuntimeService")
    def test_upstream_connection_error_returns_502(self, mock_runtime_cls):
        import requests as real_requests

        mock_runtime = MagicMock()
        mock_runtime.get_tunnel_url.return_value = "https://tunnel.modal.host"
        mock_runtime.get_connect_token.return_value = "tok"
        mock_runtime_cls.return_value = mock_runtime

        app, _sandbox = _create_running_app(self.team, self.user)

        with patch("products.streamlit_apps.backend.api.proxy.http_requests.request") as mock_req:
            mock_req.side_effect = real_requests.ConnectionError()

            response = self.client.get(self._proxy_url(app.short_id))
            assert response.status_code == 502
