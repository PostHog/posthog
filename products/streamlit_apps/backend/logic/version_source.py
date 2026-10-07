from __future__ import annotations

import os
import hashlib
import zipfile
import mimetypes
from collections.abc import Mapping, Sequence
from io import BytesIO

from products.streamlit_apps.backend.facade.contracts import (
    AppSourceFileContract,
    SourceEditError,
    SourceFileEdit,
    SourceTextEdit,
)
from products.streamlit_apps.backend.logic.zip_validator import ROOT_APP_FILE


def _entry_path(info: zipfile.ZipInfo) -> str:
    # Same normalization validate_zip uses, so "./app.py" and "app.py" name one file.
    return os.path.normpath(info.filename)


def _decode_text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _content_type(path: str, is_binary: bool) -> str:
    guessed, _ = mimetypes.guess_type(path)
    if guessed:
        return guessed
    return "application/octet-stream" if is_binary else "text/plain"


def read_source_files(zip_bytes: bytes, paths: Sequence[str] | None = None) -> list[AppSourceFileContract]:
    """List every file in a version zip. Text files carry their content; binary files do not.

    When ``paths`` is given, only those files carry content, so a large app can be read one file at a time.
    The manifest always lists every file.
    """
    wanted = set(paths) if paths is not None else None
    files: list[AppSourceFileContract] = []
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = _entry_path(info)
            data = zf.read(info)
            text = _decode_text(data)
            include_content = text is not None and (wanted is None or path in wanted)
            files.append(
                AppSourceFileContract(
                    path=path,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    content_type=_content_type(path, is_binary=text is None),
                    is_binary=text is None,
                    content=text if include_content else None,
                )
            )
    return sorted(files, key=lambda f: f.path)


def _apply_edits(text: str, edits: Sequence[SourceTextEdit], path: str) -> str:
    for index, edit in enumerate(edits):
        count = text.count(edit.old)
        if count == 0:
            raise SourceEditError(f"Edit {index} for '{path}': the old text was not found.", path, index)
        if count > 1:
            raise SourceEditError(
                f"Edit {index} for '{path}': the old text matches {count} times. Add more context to make it unique.",
                path,
                index,
            )
        text = text.replace(edit.old, edit.new, 1)
    return text


def apply_source_edits(
    zip_bytes: bytes,
    file_edits: Sequence[SourceFileEdit],
    create_files: Mapping[str, str],
    delete_files: Sequence[str],
) -> bytes:
    """Build a new version zip from ``zip_bytes`` and a set of changes.

    Every entry the changes do not touch is copied with its original bytes and zip metadata.
    """
    with zipfile.ZipFile(BytesIO(zip_bytes)) as source_zip:
        entries = [info for info in source_zip.infolist() if not info.is_dir()]
        by_path = {_entry_path(info): info for info in entries}

        for path in delete_files:
            if path == ROOT_APP_FILE:
                raise SourceEditError(f"'{ROOT_APP_FILE}' cannot be deleted.", path)
            if path not in by_path:
                raise SourceEditError(f"Cannot delete '{path}': the file does not exist in the base version.", path)
        for path in create_files:
            if path in by_path:
                raise SourceEditError(
                    f"Cannot create '{path}': the file already exists. Use file_edits to change it.", path
                )

        edited: dict[str, str] = {}
        for file_edit in file_edits:
            info = by_path.get(file_edit.path)
            if info is None:
                raise SourceEditError(
                    f"Cannot edit '{file_edit.path}': the file does not exist in the base version.", file_edit.path
                )
            text = _decode_text(source_zip.read(info))
            if text is None:
                raise SourceEditError(
                    f"Cannot edit '{file_edit.path}': binary files cannot be edited.",
                    file_edit.path,
                )
            edited[file_edit.path] = _apply_edits(text, file_edit.edits, file_edit.path)

        deleted = set(delete_files)
        result_paths = (set(by_path) - deleted) | set(create_files)
        for path in sorted(result_paths):
            if any(other.startswith(f"{path}/") for other in result_paths):
                raise SourceEditError(f"'{path}' is used as both a file and a directory.", path)

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for info in entries:
                path = _entry_path(info)
                if path in deleted:
                    continue
                if path in edited:
                    target_zip.writestr(info, edited[path].encode("utf-8"))
                else:
                    target_zip.writestr(info, source_zip.read(info))
            for path, text in create_files.items():
                target_zip.writestr(path, text)
    return buf.getvalue()
