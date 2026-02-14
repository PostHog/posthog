from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.streamlit_apps.backend.models import AllowedStreamlitPackage

EXPECTED_SEED_PACKAGES = [
    "numpy",
    "pandas",
    "polars",
    "scipy",
    "scikit-learn",
    "matplotlib",
    "seaborn",
    "plotly",
    "pyarrow",
    "duckdb",
    "requests",
    "beautifulsoup4",
    "lxml",
    "sqlalchemy",
    "streamlit",
    "streamlit-aggrid",
    "streamlit-extras",
]


class TestUpdateStreamlitPackages(BaseTest):
    def setUp(self):
        super().setUp()
        AllowedStreamlitPackage.objects.all().delete()

    def _call(self, *args):
        out, err = StringIO(), StringIO()
        call_command("update_streamlit_packages", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_add_package(self):
        out, _ = self._call("--add", "pandas>=2.0,<3.0")
        assert "Added: pandas>=2.0,<3.0" in out
        assert AllowedStreamlitPackage.objects.filter(name="pandas").exists()

    def test_add_multiple_packages(self):
        self._call("--add", "pandas", "numpy", "plotly")
        assert AllowedStreamlitPackage.objects.count() == 3

    def test_update_existing_package(self):
        AllowedStreamlitPackage.objects.create(name="pandas", version_constraint=">=1.0")
        out, _ = self._call("--add", "pandas>=2.0")
        assert "Updated: pandas>=2.0" in out
        pkg = AllowedStreamlitPackage.objects.get(name="pandas")
        assert pkg.version_constraint == ">=2.0"

    def test_remove_package(self):
        AllowedStreamlitPackage.objects.create(name="pandas")
        out, _ = self._call("--remove", "pandas")
        assert "Removed: pandas" in out
        assert not AllowedStreamlitPackage.objects.filter(name="pandas").exists()

    def test_remove_nonexistent(self):
        _, err = self._call("--remove", "nonexistent")
        assert "Not found: nonexistent" in err

    def test_list_packages(self):
        AllowedStreamlitPackage.objects.create(name="numpy")
        AllowedStreamlitPackage.objects.create(name="pandas", version_constraint=">=2.0")
        out, _ = self._call("--list")
        assert "numpy" in out
        assert "pandas>=2.0" in out

    def test_list_empty(self):
        out, _ = self._call("--list")
        assert "No packages" in out

    def test_package_names_lowercased(self):
        self._call("--add", "Pandas")
        assert AllowedStreamlitPackage.objects.filter(name="pandas").exists()


class TestSeedAllowedPackages(BaseTest):
    @parameterized.expand(EXPECTED_SEED_PACKAGES)
    def test_seed_migration_includes_package(self, package_name):
        assert AllowedStreamlitPackage.objects.filter(name=package_name).exists()

    def test_seed_migration_total_count(self):
        assert AllowedStreamlitPackage.objects.count() == len(EXPECTED_SEED_PACKAGES)
