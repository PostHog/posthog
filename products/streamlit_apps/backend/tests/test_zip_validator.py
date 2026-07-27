import zipfile
from io import BytesIO

from posthog.test.base import BaseTest

from products.streamlit_apps.backend.logic.zip_validator import MAX_ZIP_SIZE, validate_zip


def _make_zip(files: dict[str, str]) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


class TestValidateZip(BaseTest):
    def test_valid_zip_with_app_py(self):
        zf = _make_zip({"app.py": "import streamlit as st"})
        result = validate_zip(zf)
        assert result.valid is True
        assert "app.py" in result.files

    def test_valid_zip_with_requirements_does_not_fail(self):
        """requirements.txt is no longer enforced — uploads with one are
        accepted (the file is silently ignored at sandbox-write time)."""
        zf = _make_zip({"app.py": "pass", "requirements.txt": "pandas\nflask\n"})
        result = validate_zip(zf)
        assert result.valid is True

    def test_missing_app_py(self):
        zf = _make_zip({"main.py": "pass"})
        result = validate_zip(zf)
        assert result.valid is False
        assert any("app.py" in e for e in result.errors)

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

    def test_extra_files_allowed(self):
        zf = _make_zip({"app.py": "pass", "data/sample.csv": "a,b\n1,2", "assets/logo.png": "fake"})
        result = validate_zip(zf)
        assert result.valid is True
        assert len(result.files) == 3
