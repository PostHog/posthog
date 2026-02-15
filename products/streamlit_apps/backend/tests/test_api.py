import io
import uuid
import zipfile

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.streamlit_apps.backend.models import (
    AllowedStreamlitPackage,
    StreamlitApp,
    StreamlitAppSandbox,
    StreamlitAppVersion,
)


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


VALID_ZIP = _make_zip({"app.py": "import streamlit as st\nst.title('Hello')"})
ZIP_WITH_REQUIREMENTS = _make_zip(
    {
        "app.py": "import streamlit as st",
        "requirements.txt": "pandas\nnumpy\n",
    }
)


class TestStreamlitAppAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/streamlit_apps"
        if suffix:
            return f"{base}/{suffix}"
        return f"{base}/"

    def _create_app(self, **kwargs) -> StreamlitApp:
        defaults = {"team": self.team, "name": "Test App", "created_by": self.user}
        defaults.update(kwargs)
        return StreamlitApp.objects.create(**defaults)

    def _create_version(self, app: StreamlitApp, version_number: int = 1, **kwargs) -> StreamlitAppVersion:
        defaults = {
            "app": app,
            "version_number": version_number,
            "zip_file": f"streamlit_apps/{app.team_id}/{app.id}/v{version_number}.zip",
            "zip_hash": "abc123",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return StreamlitAppVersion.objects.create(**defaults)

    # -- List --

    def test_list_apps_empty(self):
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_list_apps(self):
        self._create_app(name="App A")
        self._create_app(name="App B")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

    def test_list_excludes_deleted(self):
        self._create_app(name="Visible")
        self._create_app(name="Deleted", deleted=True)
        response = self.client.get(self._url())
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["name"] == "Visible"

    def test_list_excludes_other_teams(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        self._create_app(name="My App")
        StreamlitApp.objects.create(team=other_team, name="Other App")

        response = self.client.get(self._url())
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["name"] == "My App"

    def test_list_has_status_and_viewers(self):
        app = self._create_app()
        version = self._create_version(app)
        StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="sb_123", status="running", current_viewers=3
        )
        response = self.client.get(self._url())
        result = response.json()["results"][0]
        assert result["status"] == "running"
        assert result["current_viewers"] == 3

    def test_list_stopped_status_when_no_sandbox(self):
        self._create_app()
        response = self.client.get(self._url())
        result = response.json()["results"][0]
        assert result["status"] == "stopped"
        assert result["current_viewers"] == 0

    # -- Create --

    def test_create_app(self):
        response = self.client.post(self._url(), data={"name": "New App", "description": "A new app"})
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "New App"
        assert data["description"] == "A new app"
        assert data["short_id"]
        assert data["created_by"]["id"] == self.user.id

    def test_create_app_name_required(self):
        response = self.client.post(self._url(), data={"description": "No name"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("custom_cpu", {"name": "App", "cpu_cores": 2.0}, "cpu_cores", 2.0),
            ("custom_memory", {"name": "App", "memory_gb": 4.0}, "memory_gb", 4.0),
            ("default_cpu", {"name": "App"}, "cpu_cores", 0.5),
            ("default_memory", {"name": "App"}, "memory_gb", 1.0),
        ]
    )
    def test_create_app_resource_config(self, _name, data, field, expected):
        response = self.client.post(self._url(), data=data)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()[field] == expected

    # -- Retrieve --

    def test_retrieve_app(self):
        app = self._create_app(name="Detail App", description="Details here")
        response = self.client.get(self._url(f"{app.short_id}/"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Detail App"
        assert data["description"] == "Details here"
        assert "active_version" in data
        assert "sandbox" in data

    def test_retrieve_deleted_app_404(self):
        app = self._create_app(deleted=True)
        response = self.client.get(self._url(f"{app.short_id}/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # -- Update --

    def test_update_app(self):
        app = self._create_app(name="Old Name")
        response = self.client.patch(self._url(f"{app.short_id}/"), data={"name": "New Name"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "New Name"
        app.refresh_from_db()
        assert app.name == "New Name"

    def test_update_cannot_change_short_id(self):
        app = self._create_app()
        original_short_id = app.short_id
        self.client.patch(self._url(f"{app.short_id}/"), data={"short_id": "hacked"})
        app.refresh_from_db()
        assert app.short_id == original_short_id

    # -- Delete (soft) --

    def test_delete_app_soft_deletes(self):
        app = self._create_app()
        response = self.client.delete(self._url(f"{app.short_id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        app.refresh_from_db()
        assert app.deleted is True
        assert app.deleted_at is not None

    def test_deleted_app_not_in_list(self):
        app = self._create_app()
        self.client.delete(self._url(f"{app.short_id}/"))
        response = self.client.get(self._url())
        assert len(response.json()["results"]) == 0


class TestStreamlitAppVersionAPI(APIBaseTest):
    def _url(self, short_id: str, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/streamlit_apps/{short_id}"
        if suffix:
            return f"{base}/{suffix}"
        return f"{base}/"

    def _create_app(self, **kwargs) -> StreamlitApp:
        defaults = {"team": self.team, "name": "Test App", "created_by": self.user}
        defaults.update(kwargs)
        return StreamlitApp.objects.create(**defaults)

    def _create_version(self, app: StreamlitApp, version_number: int = 1) -> StreamlitAppVersion:
        return StreamlitAppVersion.objects.create(
            app=app,
            version_number=version_number,
            zip_file=f"test/{app.id}/v{version_number}.zip",
            zip_hash="abc",
            created_by=self.user,
        )

    # -- List versions --

    def test_list_versions_empty(self):
        app = self._create_app()
        response = self.client.get(self._url(app.short_id, "versions/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_list_versions_ordered_by_version_number_desc(self):
        app = self._create_app()
        self._create_version(app, 1)
        self._create_version(app, 2)
        self._create_version(app, 3)
        response = self.client.get(self._url(app.short_id, "versions/"))
        versions = response.json()["results"]
        assert [v["version_number"] for v in versions] == [3, 2, 1]

    # -- Upload version --

    def test_upload_version(self):
        AllowedStreamlitPackage.objects.get_or_create(name="pandas")
        AllowedStreamlitPackage.objects.get_or_create(name="numpy")
        app = self._create_app()

        from django.core.files.uploadedfile import SimpleUploadedFile

        zip_file = SimpleUploadedFile("app.zip", ZIP_WITH_REQUIREMENTS, content_type="application/zip")
        response = self.client.post(
            self._url(app.short_id, "upload_version/"),
            data={"file": zip_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["version_number"] == 1
        assert data["has_requirements"] is True

        app.refresh_from_db()
        assert app.active_version_id == uuid.UUID(data["id"])

    def test_upload_version_increments_number(self):
        app = self._create_app()
        self._create_version(app, 1)

        from django.core.files.uploadedfile import SimpleUploadedFile

        zip_file = SimpleUploadedFile("app.zip", VALID_ZIP, content_type="application/zip")
        response = self.client.post(
            self._url(app.short_id, "upload_version/"),
            data={"file": zip_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["version_number"] == 2

    def test_upload_version_no_file_400(self):
        app = self._create_app()
        response = self.client.post(self._url(app.short_id, "upload_version/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No file" in response.json()["detail"]

    def test_upload_invalid_zip_400(self):
        app = self._create_app()

        from django.core.files.uploadedfile import SimpleUploadedFile

        bad_zip = SimpleUploadedFile("app.zip", b"not a zip", content_type="application/zip")
        response = self.client.post(
            self._url(app.short_id, "upload_version/"),
            data={"file": bad_zip},
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "errors" in response.json()

    def test_upload_zip_missing_app_py_400(self):
        app = self._create_app()
        zip_bytes = _make_zip({"readme.txt": "no app.py here"})

        from django.core.files.uploadedfile import SimpleUploadedFile

        zip_file = SimpleUploadedFile("app.zip", zip_bytes, content_type="application/zip")
        response = self.client.post(
            self._url(app.short_id, "upload_version/"),
            data={"file": zip_file},
            format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # -- Activate version --

    def test_activate_version(self):
        app = self._create_app()
        v1 = self._create_version(app, 1)
        v2 = self._create_version(app, 2)
        app.active_version = v2
        app.save()

        response = self.client.post(
            self._url(app.short_id, "activate_version/"),
            data={"version_number": 1},
        )
        assert response.status_code == status.HTTP_200_OK
        app.refresh_from_db()
        assert app.active_version_id == v1.id

    def test_activate_nonexistent_version_404(self):
        app = self._create_app()
        response = self.client.post(
            self._url(app.short_id, "activate_version/"),
            data={"version_number": 999},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_activate_version_requires_version_number(self):
        app = self._create_app()
        response = self.client.post(self._url(app.short_id, "activate_version/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestStreamlitAppSandboxControlAPI(APIBaseTest):
    def _url(self, short_id: str, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/streamlit_apps/{short_id}"
        if suffix:
            return f"{base}/{suffix}"
        return f"{base}/"

    def _create_app_with_version(self) -> StreamlitApp:
        app = StreamlitApp.objects.create(team=self.team, name="Test App", created_by=self.user)
        version = StreamlitAppVersion.objects.create(
            app=app, version_number=1, zip_file="test.zip", zip_hash="abc", created_by=self.user
        )
        app.active_version = version
        app.save()
        return app

    # -- Status --

    def test_status_no_sandbox(self):
        app = self._create_app_with_version()
        response = self.client.get(self._url(app.short_id, "status/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "stopped"

    def test_status_with_sandbox(self):
        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(
            app=app,
            version=app.active_version,
            sandbox_id="sb_123",
            status="running",
            current_viewers=5,
        )
        response = self.client.get(self._url(app.short_id, "status/"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "running"
        assert data["current_viewers"] == 5

    # -- Start --

    @patch("posthog.storage.object_storage.read_bytes", return_value=b"zipdata")
    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_start_app(self, mock_runtime_cls, _mock_read):
        mock_runtime = MagicMock()
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "start/"))
        assert response.status_code == status.HTTP_200_OK
        mock_runtime.start_app.assert_called_once()

    def test_start_app_no_version_400(self):
        app = StreamlitApp.objects.create(team=self.team, name="No Version", created_by=self.user)
        response = self.client.post(self._url(app.short_id, "start/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No active version" in response.json()["detail"]

    @patch("posthog.storage.object_storage.read_bytes", return_value=b"zipdata")
    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_start_app_runtime_error_503(self, mock_runtime_cls, _mock_read):
        mock_runtime = MagicMock()
        mock_runtime.start_app.side_effect = RuntimeError("Modal down")
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "start/"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    # -- Stop --

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_stop_app(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "stop/"))
        assert response.status_code == status.HTTP_200_OK
        mock_runtime.stop_app.assert_called_once_with(app)

    # -- Restart --

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_restart_app(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "restart/"))
        assert response.status_code == status.HTTP_200_OK
        mock_runtime.restart_app.assert_called_once_with(app)

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_restart_runtime_error_503(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.restart_app.side_effect = RuntimeError("Restart failed")
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "restart/"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    # -- Connect URL --

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_connect_url_returns_url_and_token(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://abc.modal.run", "token": "tok_123"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        response = self.client.get(self._url(app.short_id, "connect_url/"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["url"] == "https://abc.modal.run"
        assert data["token"] == "tok_123"

    def test_connect_url_not_running_returns_503(self):
        app = self._create_app_with_version()
        response = self.client.get(self._url(app.short_id, "connect_url/"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_connect_url_at_max_viewers_returns_503(self, mock_runtime_cls):
        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(
            app=app,
            version=app.active_version,
            sandbox_id="sb_1",
            status="running",
            current_viewers=20,
            max_viewers=20,
        )

        response = self.client.get(self._url(app.short_id, "connect_url/"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "busy" in response.json()["detail"].lower()

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_connect_url_updates_last_activity(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://x.modal.run", "token": "tok"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app, version=app.active_version, sandbox_id="sb_1", status="running"
        )
        assert sandbox_record.last_activity_at is None

        self.client.get(self._url(app.short_id, "connect_url/"))
        sandbox_record.refresh_from_db()
        assert sandbox_record.last_activity_at is not None

    @patch("products.streamlit_apps.backend.api.streamlit_app.AppRuntimeService")
    def test_connect_url_runtime_failure_returns_502(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = None
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        response = self.client.get(self._url(app.short_id, "connect_url/"))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
