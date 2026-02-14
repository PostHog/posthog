import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.streamlit_apps.backend.models import (
    AllowedStreamlitPackage,
    StreamlitApp,
    StreamlitAppSandbox,
    StreamlitAppVersion,
)


class TestStreamlitAppModel(BaseTest):
    def test_create_app(self):
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            description="A test app",
            created_by=self.user,
        )
        assert app.short_id
        assert app.name == "Test App"
        assert app.cpu_cores == 0.5
        assert app.memory_gb == 1
        assert app.deleted is False
        assert app.active_version is None

    def test_short_id_auto_generated(self):
        app1 = StreamlitApp.objects.create(team=self.team, name="App 1")
        app2 = StreamlitApp.objects.create(team=self.team, name="App 2")
        assert app1.short_id != app2.short_id

    def test_str(self):
        app = StreamlitApp.objects.create(team=self.team, name="My App")
        assert str(app) == "My App"


class TestStreamlitAppVersionModel(BaseTest):
    def test_create_version(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(
            app=app,
            version_number=1,
            zip_file="s3://bucket/path.zip",
            zip_hash="abc123",
            has_requirements=True,
            packages=["pandas", "numpy"],
            created_by=self.user,
        )
        assert version.version_number == 1
        assert version.snapshot_id is None
        assert version.packages == ["pandas", "numpy"]

    def test_unique_version_per_app(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        with pytest.raises(Exception):
            StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="b.zip", zip_hash="b")

    def test_ordering_by_version_number_desc(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppVersion.objects.create(app=app, version_number=3, zip_file="c.zip", zip_hash="c")
        StreamlitAppVersion.objects.create(app=app, version_number=2, zip_file="b.zip", zip_hash="b")
        versions = list(app.versions.values_list("version_number", flat=True))
        assert versions == [3, 2, 1]

    def test_str(self):
        app = StreamlitApp.objects.create(team=self.team, name="My App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=5, zip_file="a.zip", zip_hash="a")
        assert str(version) == "My App v5"


class TestStreamlitAppSandboxModel(BaseTest):
    @parameterized.expand(
        [
            ("starting", StreamlitAppSandbox.Status.STARTING),
            ("running", StreamlitAppSandbox.Status.RUNNING),
            ("stopping", StreamlitAppSandbox.Status.STOPPING),
            ("stopped", StreamlitAppSandbox.Status.STOPPED),
            ("error", StreamlitAppSandbox.Status.ERROR),
        ]
    )
    def test_sandbox_status_choices(self, status_value, status_enum):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        sandbox = StreamlitAppSandbox.objects.create(
            app=app, version=version, sandbox_id="modal-123", status=status_enum
        )
        assert sandbox.status == status_value

    def test_one_sandbox_per_app(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="modal-1")
        with pytest.raises(Exception):
            StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="modal-2")

    def test_defaults(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        sandbox = StreamlitAppSandbox.objects.create(app=app, version=version, sandbox_id="modal-1")
        assert sandbox.restart_count == 0
        assert sandbox.current_viewers == 0
        assert sandbox.max_viewers == 20


class TestAllowedStreamlitPackageModel(BaseTest):
    def test_create_package(self):
        pkg = AllowedStreamlitPackage.objects.create(name="pandas", version_constraint=">=2.0,<3.0")
        assert str(pkg) == "pandas>=2.0,<3.0"

    def test_str_without_constraint(self):
        pkg = AllowedStreamlitPackage.objects.create(name="numpy")
        assert str(pkg) == "numpy"

    def test_unique_package_name(self):
        AllowedStreamlitPackage.objects.create(name="pandas")
        with pytest.raises(Exception):
            AllowedStreamlitPackage.objects.create(name="pandas")

    def test_active_version_relationship(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        version = StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        app.active_version = version
        app.save()
        app.refresh_from_db()
        assert app.active_version == version

    def test_cascade_delete_versions(self):
        app = StreamlitApp.objects.create(team=self.team, name="Test App")
        StreamlitAppVersion.objects.create(app=app, version_number=1, zip_file="a.zip", zip_hash="a")
        StreamlitAppVersion.objects.create(app=app, version_number=2, zip_file="b.zip", zip_hash="b")
        app.delete()
        assert StreamlitAppVersion.objects.count() == 0
