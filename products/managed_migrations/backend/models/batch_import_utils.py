from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from posthog.models.user import User


def redact_part_key(key: object) -> object:
    """Strip credential-bearing URL components from a worker part key.

    url_list imports use full source URLs as part keys, and those URLs live in the
    encrypted secrets column precisely because they can embed presigned tokens
    (query string) or basic-auth credentials (userinfo). The worker copies them
    verbatim into the plaintext state blob, so anything that surfaces a part key
    must redact those components. Scheme/host/path are kept so the part stays
    identifiable; non-URL keys (S3 object keys, date ranges, file paths) pass
    through unchanged, as do non-string values from a malformed state blob.
    """
    if not isinstance(key, str) or "://" not in key:
        return key
    try:
        parts = urlsplit(key)
        if not parts.scheme or not parts.netloc:
            return key
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        # Unparseable URL-ish key (e.g. bad port/IPv6): fail closed rather than leak.
        return "[unparseable-url-redacted]"


def extract_batch_import_info(batch_import) -> tuple[str, str, Optional[str], Optional[str]]:
    """Extract source type, content type, start date, and end date from BatchImport"""
    source_type = "unknown"
    content_type = "unknown"
    start_date = None
    end_date = None

    if batch_import.import_config:
        source = batch_import.import_config.get("source", {})
        source_type = source.get("type", "unknown")
        start_date = source.get("start")
        end_date = source.get("end")

        data_format = batch_import.import_config.get("data_format", {})
        content = data_format.get("content", {})
        content_type = content.get("type", "unknown")

    return source_type, content_type, start_date, end_date


def get_batch_import_created_by_info(batch_import) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Get created by user information from BatchImport"""
    created_by_user_id = None
    created_by_user_email = None
    created_by_user_name = None

    if batch_import.created_by_id:
        try:
            user_obj = User.objects.get(id=batch_import.created_by_id)
            created_by_user_id = str(user_obj.id)
            created_by_user_email = user_obj.email
            created_by_user_name = f"{user_obj.first_name} {user_obj.last_name}".strip()
        except User.DoesNotExist:
            pass

    return created_by_user_id, created_by_user_email, created_by_user_name


def get_batch_import_detail_name(source_type: str, content_type: str) -> str:
    """Generate detail name for BatchImport activity"""
    return f"{source_type} ({content_type})"
