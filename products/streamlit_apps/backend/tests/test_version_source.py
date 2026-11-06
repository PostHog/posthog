import io
import hashlib
import zipfile

import pytest

from parameterized import parameterized

from products.streamlit_apps.backend.facade.contracts import SourceEditError, SourceFileEdit, SourceTextEdit
from products.streamlit_apps.backend.logic.version_source import apply_source_edits, read_source_files

PARQUET_BYTES = b"PAR1\x00\x01\x02\xff"
APP_SOURCE = "import streamlit as st\nst.title('Old')\n"
UTILS_SOURCE = "def helper():\n    return 1\n"


def _zip(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


BASE_ZIP = _zip({"app.py": APP_SOURCE, "utils.py": UTILS_SOURCE, "data/events.parquet": PARQUET_BYTES})


def _contents(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist()}


def _edit(path: str, *pairs: tuple[str, str]) -> SourceFileEdit:
    return SourceFileEdit(path=path, edits=[SourceTextEdit(old=old, new=new) for old, new in pairs])


class TestReadSourceFiles:
    def test_lists_every_file_and_inlines_only_text(self):
        files = {f.path: f for f in read_source_files(BASE_ZIP)}

        assert sorted(files) == ["app.py", "data/events.parquet", "utils.py"]
        assert files["app.py"].content == APP_SOURCE
        assert files["app.py"].sha256 == hashlib.sha256(APP_SOURCE.encode()).hexdigest()
        assert files["data/events.parquet"].is_binary
        assert files["data/events.parquet"].content is None
        assert files["data/events.parquet"].size == len(PARQUET_BYTES)

    def test_paths_filter_keeps_full_manifest(self):
        files = {f.path: f for f in read_source_files(BASE_ZIP, paths=["utils.py"])}

        assert sorted(files) == ["app.py", "data/events.parquet", "utils.py"]
        assert files["utils.py"].content == UTILS_SOURCE
        assert files["app.py"].content is None


class TestApplySourceEdits:
    def test_untouched_files_keep_their_bytes(self):
        result = _contents(
            apply_source_edits(
                BASE_ZIP,
                file_edits=[_edit("app.py", ("'Old'", "'New'"))],
                create_files={"pages/extra.py": "print(1)\n"},
                delete_files=["utils.py"],
            )
        )

        assert result == {
            "app.py": APP_SOURCE.replace("'Old'", "'New'").encode(),
            "data/events.parquet": PARQUET_BYTES,
            "pages/extra.py": b"print(1)\n",
        }

    def test_edits_apply_in_order(self):
        result = _contents(apply_source_edits(BASE_ZIP, [_edit("app.py", ("Old", "Mid"), ("Mid", "New"))], {}, []))

        assert result["app.py"] == APP_SOURCE.replace("Old", "New").encode()

    def test_reads_entries_with_dot_prefix(self):
        stored = _zip({"./app.py": APP_SOURCE})

        result = _contents(apply_source_edits(stored, [_edit("app.py", ("Old", "New"))], {}, []))

        assert result == {"./app.py": APP_SOURCE.replace("Old", "New").encode()}

    @parameterized.expand(
        [
            ("old_not_found", [_edit("app.py", ("missing", "x"))], {}, [], "app.py", 0),
            ("old_matches_twice", [_edit("app.py", ("Old", "Mid"), ("st", "x"))], {}, [], "app.py", 1),
            ("empty_old_on_nonempty_file", [_edit("app.py", ("", "x"))], {}, [], "app.py", 0),
            ("edit_missing_file", [_edit("gone.py", ("a", "b"))], {}, [], "gone.py", None),
            ("edit_binary_file", [_edit("data/events.parquet", ("PAR1", "x"))], {}, [], "data/events.parquet", None),
            ("create_existing_file", [], {"utils.py": "x"}, [], "utils.py", None),
            ("delete_app_py", [], {}, ["app.py"], "app.py", None),
            ("delete_missing_file", [], {}, ["gone.py"], "gone.py", None),
            ("create_under_existing_file", [], {"utils.py/x.py": "x"}, [], "utils.py", None),
        ]
    )
    def test_rejects_invalid_changes(self, _name, file_edits, create_files, delete_files, path, edit_index):
        with pytest.raises(SourceEditError) as exc_info:
            apply_source_edits(BASE_ZIP, file_edits, create_files, delete_files)

        assert exc_info.value.path == path
        assert exc_info.value.edit_index == edit_index
