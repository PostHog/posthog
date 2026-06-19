from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILE_COUNT = 500


def _format_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def is_safe_zip_path(filename: str) -> bool:
    """Check if a zip entry filename is safe (no path traversal)."""
    normalized = os.path.normpath(filename)
    return not (normalized.startswith("..") or normalized.startswith("/"))


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def validate_zip(file: BytesIO) -> ValidationResult:
    """Validate an uploaded zip file for Streamlit app structure."""
    result = ValidationResult(valid=True)

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    # Compressed (on-disk) size check; uncompressed size is validated below.
    if size > MAX_ZIP_SIZE:
        result.valid = False
        result.errors.append(f"Zip file too large ({_format_mb(size)}, max {_format_mb(MAX_ZIP_SIZE)})")
        return result

    try:
        with zipfile.ZipFile(file) as zf:
            infolist = zf.infolist()

            non_dir_entries = [info for info in infolist if not info.is_dir()]
            total_uncompressed = sum(info.file_size for info in non_dir_entries)
            if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
                result.valid = False
                result.errors.append(
                    f"Total uncompressed size too large "
                    f"({_format_mb(total_uncompressed)}, max {_format_mb(MAX_UNCOMPRESSED_SIZE)})"
                )
                return result
            if len(non_dir_entries) > MAX_FILE_COUNT:
                result.valid = False
                result.errors.append(f"Too many files: {len(non_dir_entries)} (max {MAX_FILE_COUNT})")
                return result

            for info in non_dir_entries:
                if not is_safe_zip_path(info.filename):
                    result.valid = False
                    result.errors.append(f"Unsafe file path: {info.filename}")

            if not result.valid:
                return result

            result.files = [os.path.normpath(info.filename) for info in non_dir_entries]

            actual_total = 0
            for info in non_dir_entries:
                with zf.open(info.filename) as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > MAX_UNCOMPRESSED_SIZE:
                            result.valid = False
                            result.errors.append(
                                f"Total uncompressed size too large (exceeded {_format_mb(MAX_UNCOMPRESSED_SIZE)})"
                            )
                            return result

            if "app.py" not in result.files:
                result.valid = False
                result.errors.append("Missing required Streamlit app file at root of the zip: app.py")
    except zipfile.BadZipFile:
        result.valid = False
        result.errors.append("Invalid zip file")

    return result
