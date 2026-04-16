"""Compatibility shim for symbol set API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingSymbolSetSerializer,
    ErrorTrackingSymbolSetUploadSerializer,
    SymbolSetUpload,
)
from products.error_tracking.backend.presentation.views import (
    JS_DATA_MAGIC,
    JS_DATA_TYPE_SOURCE_AND_MAP,
    JS_DATA_VERSION,
    ONE_HUNDRED_MEGABYTES,
    PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
    ErrorTrackingSymbolSetViewSet,
    bulk_create_symbol_sets,
    construct_js_data_object,
    create_symbol_set,
    generate_symbol_set_file_key,
    generate_symbol_set_upload_presigned_url,
    upload_content,
)

__all__ = [
    "ONE_HUNDRED_MEGABYTES",
    "JS_DATA_MAGIC",
    "JS_DATA_VERSION",
    "JS_DATA_TYPE_SOURCE_AND_MAP",
    "PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT",
    "SymbolSetUpload",
    "ErrorTrackingSymbolSetUploadSerializer",
    "ErrorTrackingSymbolSetSerializer",
    "ErrorTrackingSymbolSetViewSet",
    "create_symbol_set",
    "bulk_create_symbol_sets",
    "upload_content",
    "construct_js_data_object",
    "generate_symbol_set_file_key",
    "generate_symbol_set_upload_presigned_url",
]
