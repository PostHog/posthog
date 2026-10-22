from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_VIRTUAL_HOST_RE = re.compile(r"^(?P<bucket>[a-z0-9][a-z0-9.\-]*)\.s3(?:[.\-][a-z0-9\-]+)?\.amazonaws\.com$")
_PATH_STYLE_HOST_RE = re.compile(r"^s3(?:[.\-][a-z0-9\-]+)?\.amazonaws\.com$")
_GLOB_CHARS = frozenset("*?[]{}")


def normalize_s3_location(location: str) -> str | None:
    """Return ``s3://<bucket>/<key>`` with no trailing slash, or None for anything that is not an S3 object path.

    Accepts ``s3://`` and ``s3a://`` URIs and AWS virtual-hosted or path-style HTTPS URLs, so the same
    files compare equal however a table recorded them.
    """
    parts = urlsplit(location.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme in ("s3", "s3a"):
        bucket, key = parts.netloc, parts.path
    elif scheme in ("http", "https"):
        path = unquote(parts.path)
        virtual_host = _VIRTUAL_HOST_RE.match(host)
        if virtual_host is not None:
            bucket, key = virtual_host.group("bucket"), path
        elif _PATH_STYLE_HOST_RE.match(host):
            bucket, _, key = path.lstrip("/").partition("/")
        else:
            return None
    else:
        return None

    key = key.strip("/")
    if not bucket or not key:
        return None
    return f"s3://{bucket}/{key}"


def delta_table_root(url_pattern: str) -> str | None:
    """The normalized root of a Delta table, or None when the URL cannot name one.

    A glob names a set of files, not a Delta table, so it never maps.
    """
    if any(char in _GLOB_CHARS for char in url_pattern):
        return None
    root = normalize_s3_location(url_pattern)
    if root is None:
        return None
    root = root.removesuffix("/_delta_log")
    return root if root.count("/") > 2 else None
