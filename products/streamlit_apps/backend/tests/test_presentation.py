import io
import uuid
import zipfile
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox, StreamlitAppVersion


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


class _StreamlitAppsFlagMixin:
    """Shared test setup that mocks the `streamlit-apps` feature flag.

    StreamlitAppsAccessPermission hides the whole viewset behind the flag,
    so every test class that talks to the viewset needs to opt in. Default
    every test to "flag enabled" so the existing assertions keep working;
    the one flag-gating test flips it back off explicitly.
    """

    _flag_patcher: Any

    def setUp(self):
        super().setUp()  # type: ignore[misc]
        self._set_streamlit_apps_flag(True)

    def tearDown(self):
        if hasattr(self, "_flag_patcher"):
            self._flag_patcher.stop()
        super().tearDown()  # type: ignore[misc]

    def _set_streamlit_apps_flag(self, enabled: bool) -> None:
        if hasattr(self, "_flag_patcher"):
            self._flag_patcher.stop()
        self._flag_patcher = patch("posthoganalytics.feature_enabled")
        mock = self._flag_patcher.start()

        def check_flag(flag_name, *_args, **_kwargs):
            # Match ONLY the streamlit-apps flag: returning True for all flag
            # names would spuriously enable unrelated flags that other code
            # in the stack evaluates during the same request.
            if flag_name == "streamlit-apps":
                return enabled
            return False

        mock.side_effect = check_flag


class TestStreamlitAppAPI(_StreamlitAppsFlagMixin, APIBaseTest):
    # The viewset is registered under /projects/ via the product's routes.py.
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

    def test_list_has_status(self):
        app = self._create_app()
        version = self._create_version(app)
        StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="sb_123", status="running")
        response = self.client.get(self._url())
        result = response.json()["results"][0]
        assert result["status"] == "running"

    def test_list_returns_403_when_feature_flag_disabled(self):
        # StreamlitAppsAccessPermission hides the whole viewset behind the
        # `streamlit-apps` PostHog flag; when the flag is off, even listing
        # should 403 regardless of team membership.
        self._set_streamlit_apps_flag(False)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stopped_status_when_no_sandbox(self):
        self._create_app()
        response = self.client.get(self._url())
        result = response.json()["results"][0]
        assert result["status"] == "stopped"

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


class TestStreamlitAppVersionAPI(_StreamlitAppsFlagMixin, APIBaseTest):
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

    @patch("posthog.storage.object_storage.write")
    def test_upload_version_with_requirements_silently_accepted(self, mock_storage_write):
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
        mock_storage_write.assert_called_once()

        app.refresh_from_db()
        assert app.active_version_id == uuid.UUID(data["id"])

    @patch("posthog.storage.object_storage.write")
    def test_upload_version_increments_number(self, mock_storage_write):
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
        mock_storage_write.assert_called_once()

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
        assert "Invalid zip" in response.json()["detail"]

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

    @patch("posthog.storage.object_storage.write")
    def test_upload_version_stops_live_sandbox(self, _mock_storage_write):
        """Uploading a new version implicitly activates it, so any running
        sandbox is now serving stale code and must be stopped."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        app = self._create_app()
        v1 = self._create_version(app, 1)
        app.active_version = v1
        app.save()
        StreamlitAppSandbox.objects.create(
            app=app, version=v1, sandbox_id="sb_old", status=StreamlitAppSandbox.Status.RUNNING
        )

        zip_file = SimpleUploadedFile("app.zip", VALID_ZIP, content_type="application/zip")
        with patch("products.streamlit_apps.backend.facade.api.AppRuntimeService") as runtime_cls:
            response = self.client.post(
                self._url(app.short_id, "upload_version/"),
                data={"file": zip_file},
                format="multipart",
            )

        assert response.status_code == status.HTTP_201_CREATED
        runtime_cls.return_value.stop_app.assert_called_once_with(app)

    def test_activate_version_returns_new_active_version(self):
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
        data = response.json()
        assert data["active_version"]["version_number"] == 1
        # The server now stops the sandbox itself, so callers no longer need a
        # `requires_restart` hint.
        assert "requires_restart" not in data
        app.refresh_from_db()
        assert app.active_version_id == v1.id

    @parameterized.expand(
        [
            (StreamlitAppSandbox.Status.RUNNING, True),
            (StreamlitAppSandbox.Status.STARTING, True),
            (StreamlitAppSandbox.Status.STOPPED, False),
            (StreamlitAppSandbox.Status.STOPPING, False),
            (StreamlitAppSandbox.Status.ERROR, False),
        ]
    )
    def test_activate_version_stops_live_sandbox(self, sandbox_status, should_stop):
        app = self._create_app()
        self._create_version(app, 1)
        v2 = self._create_version(app, 2)
        app.active_version = v2
        app.save()
        StreamlitAppSandbox.objects.create(app=app, version=v2, sandbox_id="sb_old", status=sandbox_status)

        with patch("products.streamlit_apps.backend.facade.api.AppRuntimeService") as runtime_cls:
            response = self.client.post(
                self._url(app.short_id, "activate_version/"),
                data={"version_number": 1},
            )

        assert response.status_code == status.HTTP_200_OK
        if should_stop:
            runtime_cls.return_value.stop_app.assert_called_once_with(app)
        else:
            runtime_cls.return_value.stop_app.assert_not_called()

    def test_activate_version_swallows_stop_failure(self):
        """Stop is best-effort: a Modal/runtime hiccup must not break activation."""
        app = self._create_app()
        v1 = self._create_version(app, 1)
        v2 = self._create_version(app, 2)
        app.active_version = v2
        app.save()
        StreamlitAppSandbox.objects.create(
            app=app, version=v2, sandbox_id="sb_old", status=StreamlitAppSandbox.Status.RUNNING
        )

        with patch("products.streamlit_apps.backend.facade.api.AppRuntimeService") as runtime_cls:
            runtime_cls.return_value.stop_app.side_effect = RuntimeError("Modal down")
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

    @parameterized.expand([("string", "abc"), ("float", 1.5), ("bool", True)])
    def test_activate_version_rejects_non_integer(self, _name, version_number):
        # A non-integer would otherwise hit the ORM and raise a 500 rather than a 400.
        app = self._create_app()
        self._create_version(app, 1)
        response = self.client.post(
            self._url(app.short_id, "activate_version/"),
            data={"version_number": version_number},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.storage.object_storage.write")
    def test_upload_version_too_large_413(self, mock_storage_write):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from products.streamlit_apps.backend.logic.zip_validator import MAX_ZIP_SIZE

        app = self._create_app()
        oversized = SimpleUploadedFile("app.zip", b"\0" * (MAX_ZIP_SIZE + 1), content_type="application/zip")
        response = self.client.post(
            self._url(app.short_id, "upload_version/"),
            data={"file": oversized},
            format="multipart",
        )
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        # The body is rejected by size before it is ever read or persisted.
        mock_storage_write.assert_not_called()


class TestStreamlitAppSandboxControlAPI(_StreamlitAppsFlagMixin, APIBaseTest):
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
        )
        response = self.client.get(self._url(app.short_id, "status/"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "running"

    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_start_app_dispatches_task(self, mock_delay):
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "start/"))
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_delay.assert_called_once_with(str(app.id), "start", team_id=app.team_id)

    def test_start_app_no_version_400(self):
        app = StreamlitApp.objects.create(team=self.team, name="No Version", created_by=self.user)
        response = self.client.post(self._url(app.short_id, "start/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No active version" in response.json()["detail"]

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_stop_app(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime_cls.return_value = mock_runtime
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "stop/"))
        assert response.status_code == status.HTTP_200_OK
        mock_runtime.stop_app.assert_called_once_with(app)

    @patch("products.streamlit_apps.backend.tasks.run_streamlit_app_lifecycle.delay")
    def test_restart_app_dispatches_task(self, mock_delay):
        app = self._create_app_with_version()

        response = self.client.post(self._url(app.short_id, "restart/"))
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_delay.assert_called_once_with(str(app.id), "restart", team_id=app.team_id)

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_returns_iframe_url_with_tokens(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://abc.modal.run", "token": "tok_123"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        response = self.client.get(self._url(app.short_id, "connect_info/"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "iframe_url" in data
        assert "expires_in" in data
        assert "https://abc.modal.run" in data["iframe_url"]
        assert "_posthog_token=" in data["iframe_url"]
        assert "_modal_connect_token=tok_123" in data["iframe_url"]
        # expires_in is the REAL remaining lifetime of the minted iframe token
        # (max 3600s for a freshly minted token, strictly less once clock drifts).
        # Allow a small tolerance because the token is minted and then the expires
        # datetime is recomputed a few ms later in the view.
        assert 3590 <= data["expires_in"] <= 3600

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_omits_modal_token_when_none(self, mock_runtime_cls):
        # Docker sandboxes have no Modal connect token (token=None). The iframe
        # URL must not embed the literal string "None" as a token.
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "http://localhost:49153", "token": None}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        response = self.client.get(self._url(app.short_id, "connect_info/"))
        assert response.status_code == status.HTTP_200_OK
        iframe_url = response.json()["iframe_url"]
        assert "None" not in iframe_url
        assert "_modal_connect_token=None" not in iframe_url
        assert "_posthog_token=" in iframe_url

    def test_connect_info_not_running_returns_503(self):
        app = self._create_app_with_version()
        response = self.client.get(self._url(app.short_id, "connect_info/"))
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_updates_last_activity(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://x.modal.run", "token": "tok"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app, version=app.active_version, sandbox_id="sb_1", status="running"
        )
        assert sandbox_record.last_activity_at is None

        self.client.get(self._url(app.short_id, "connect_info/"))
        sandbox_record.refresh_from_db()
        assert sandbox_record.last_activity_at is not None

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_debounces_last_activity_writes(self, mock_runtime_cls):
        """connect_info is polled every ~2 seconds by the frontend token
        refresher; writing last_activity_at on every call used to translate
        to a per-sandbox row update every 2 seconds per active viewer. The
        write is now debounced to once per _LAST_ACTIVITY_DEBOUNCE_SECONDS."""
        from datetime import timedelta

        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://x.modal.run", "token": "tok"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        recent = timezone.now() - timedelta(seconds=5)
        sandbox_record = StreamlitAppSandbox.objects.create(
            app=app,
            version=app.active_version,
            sandbox_id="sb_1",
            status="running",
            last_activity_at=recent,
        )

        self.client.get(self._url(app.short_id, "connect_info/"))
        sandbox_record.refresh_from_db()
        # last_activity_at is still the old value — the second call was
        # within the debounce window and skipped the UPDATE.
        assert sandbox_record.last_activity_at == recent

        # Rewind the last_activity_at past the debounce window and retry.
        stale = timezone.now() - timedelta(seconds=120)
        StreamlitAppSandbox.objects.filter(id=sandbox_record.id).update(last_activity_at=stale)
        self.client.get(self._url(app.short_id, "connect_info/"))
        sandbox_record.refresh_from_db()
        assert sandbox_record.last_activity_at > stale

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_runtime_failure_returns_502(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = None
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        response = self.client.get(self._url(app.short_id, "connect_info/"))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_creates_oauth_token(self, mock_runtime_cls):
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://abc.modal.run", "token": "tok"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        from posthog.models.oauth import OAuthAccessToken

        initial_count = OAuthAccessToken.objects.filter(user=self.user).count()

        self.client.get(self._url(app.short_id, "connect_info/"))

        assert OAuthAccessToken.objects.filter(user=self.user).count() == initial_count + 1
        token = OAuthAccessToken.objects.filter(user=self.user).order_by("-id").first()
        assert token.scoped_teams == [self.team.id]
        # Iframe-scoped — must NOT be a bridge token, so a stolen iframe URL
        # can't be replayed against the streamlit bridge endpoint.
        assert token.scope == "streamlit:iframe"

    @patch("products.streamlit_apps.backend.facade.api.AppRuntimeService")
    def test_connect_info_reuses_existing_token(self, mock_runtime_cls):
        """A second connect_info call within the reuse window should reuse
        the existing token rather than minting a fresh one — this is what
        keeps the OAuth token table from growing on every iframe poll."""
        mock_runtime = MagicMock()
        mock_runtime.get_connect_url.return_value = {"url": "https://abc.modal.run", "token": "tok"}
        mock_runtime_cls.return_value = mock_runtime

        app = self._create_app_with_version()
        StreamlitAppSandbox.objects.create(app=app, version=app.active_version, sandbox_id="sb_1", status="running")

        from posthog.models.oauth import OAuthAccessToken

        self.client.get(self._url(app.short_id, "connect_info/"))
        first_count = OAuthAccessToken.objects.filter(user=self.user).count()

        self.client.get(self._url(app.short_id, "connect_info/"))
        second_count = OAuthAccessToken.objects.filter(user=self.user).count()

        assert first_count == second_count, "expected token reuse, but a new token was minted"
