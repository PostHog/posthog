"""Re-export of the shared file-upload storage contract.

The key layout and format list are source-agnostic (the upload endpoint writes them too), so they
live in ``products/warehouse_sources/backend/file_uploads.py``. This module keeps the usual
``sources/<name>/settings.py`` entry point pointing at them.
"""

from products.warehouse_sources.backend.file_uploads import (
    FILE_UPLOADS_FOLDER,
    FORMAT_CSV,
    FORMAT_JSON,
    FORMAT_PARQUET,
    MAX_UPLOAD_SIZE_BYTES,
    SUPPORTED_FILE_FORMATS,
    build_file_upload_s3_key,
    build_file_upload_s3_path,
    build_file_upload_s3_prefix,
    build_file_upload_s3_uri,
)

__all__ = [
    "FILE_UPLOADS_FOLDER",
    "FORMAT_CSV",
    "FORMAT_JSON",
    "FORMAT_PARQUET",
    "MAX_UPLOAD_SIZE_BYTES",
    "SUPPORTED_FILE_FORMATS",
    "build_file_upload_s3_key",
    "build_file_upload_s3_path",
    "build_file_upload_s3_prefix",
    "build_file_upload_s3_uri",
]
