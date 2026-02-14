import zipfile
from io import BytesIO

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.streamlit_apps.backend.models import AllowedStreamlitPackage
from products.streamlit_apps.backend.services.zip_validator import MAX_ZIP_SIZE, validate_zip


def _make_zip(files: dict[str, str]) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


class TestValidateZip(BaseTest):
    def setUp(self):
        super().setUp()
        AllowedStreamlitPackage.objects.all().delete()
        AllowedStreamlitPackage.objects.create(name="pandas")
        AllowedStreamlitPackage.objects.create(name="numpy")

    def test_valid_zip_with_app_py(self):
        zf = _make_zip({"app.py": "import streamlit as st"})
        result = validate_zip(zf)
        assert result.valid is True
        assert "app.py" in result.files

    def test_valid_zip_with_requirements(self):
        zf = _make_zip({"app.py": "pass", "requirements.txt": "pandas\nnumpy\n"})
        result = validate_zip(zf)
        assert result.valid is True
        assert result.has_requirements is True
        assert result.packages == ["pandas", "numpy"]

    def test_missing_app_py(self):
        zf = _make_zip({"main.py": "pass"})
        result = validate_zip(zf)
        assert result.valid is False
        assert any("app.py" in e for e in result.errors)

    def test_disallowed_package(self):
        zf = _make_zip({"app.py": "pass", "requirements.txt": "flask\n"})
        result = validate_zip(zf)
        assert result.valid is False
        assert any("flask" in e for e in result.errors)

    def test_too_large(self):
        buf = BytesIO(b"x" * (MAX_ZIP_SIZE + 1))
        result = validate_zip(buf)
        assert result.valid is False
        assert any("too large" in e for e in result.errors)

    def test_invalid_zip(self):
        buf = BytesIO(b"not a zip file")
        result = validate_zip(buf)
        assert result.valid is False
        assert any("Invalid zip" in e for e in result.errors)

    def test_comments_and_blanks_in_requirements(self):
        zf = _make_zip({"app.py": "pass", "requirements.txt": "# comment\n\npandas\n"})
        result = validate_zip(zf)
        assert result.valid is True
        assert result.packages == ["pandas"]

    @parameterized.expand(
        [
            ("with_version", "pandas>=2.0", True),
            ("with_extras", "unknown_pkg", False),
            ("mixed", "pandas\nunknown_pkg", False),
        ]
    )
    def test_requirements_validation(self, _name, requirements, expected_valid):
        zf = _make_zip({"app.py": "pass", "requirements.txt": requirements})
        result = validate_zip(zf)
        assert result.valid is expected_valid

    def test_extra_files_allowed(self):
        zf = _make_zip({"app.py": "pass", "data/sample.csv": "a,b\n1,2", "assets/logo.png": "fake"})
        result = validate_zip(zf)
        assert result.valid is True
        assert len(result.files) == 3
