"""URL helpers used by the tracked HTTP transport.

`scrub_url` redacts auth-bearing query parameters before a URL is logged
or written into a captured sample: query values for matching keys are
replaced with `REDACTED`. The path is otherwise preserved verbatim, except
for segments that look like an email address, which become `{email}` —
some APIs take an address as a lookup key, and it is personal data.

`url_template` returns a low-cardinality variant where path segments that
look like IDs are replaced with `{id}`. We don't use it for log fields any
more (the user asked for full URLs in logs) but still emit it alongside
so that aggregation queries against the log_entries table have a stable
group-by.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

_REDACT_PARAM_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Generic auth/secret param names
        "api_key",
        "apikey",
        "appid",  # OpenWeather passes the API key as the `appid` query param
        "access_token",
        "auth",
        "auth_token",
        "key",
        "password",
        "secret",
        "sig",
        "signature",
        "token",
        # OAuth 2.0 / token-exchange flow params (RFC 6749 / RFC 7521 / OIDC).
        # These are usually sent in form bodies but can also appear in URLs;
        # we cover them here so the same denylist serves both `scrub_url` and
        # the form-urlencoded body scrubber in `sampling.py`.
        "client_secret",
        "client_assertion",
        "client_assertion_type",
        "code",
        "code_verifier",
        "id_token",
        "id_token_hint",
        "refresh_token",
        "subject_token",
        "actor_token",
    }
)

_REDACTED: Final[str] = "REDACTED"

# Below this length a credential is too short to redact by value without risking
# mangling unrelated log text; real API keys/tokens are far longer.
_MIN_REDACT_VALUE_LEN: Final[int] = 4


def redact_literal_values(text: str, values: Iterable[str]) -> str:
    """Replace known secret values (and their URL-encoded forms) with REDACTED.

    Complements the name-based `scrub_url`/header denylists: when a manifest puts
    a credential in a query param, header, or cookie whose name we can't predict,
    the value is still masked here because we know the exact credential string.
    This is value-based masking (cf. Airbyte) — it covers any injection location
    and any param name. Both the raw and percent-encoded forms are matched since
    a query value is URL-encoded by the time it reaches the logged URL.
    """
    for value in values:
        if not value or len(value) < _MIN_REDACT_VALUE_LEN:
            continue
        for variant in {value, quote(value, safe=""), quote_plus(value)}:
            text = text.replace(variant, _REDACTED)
    return text


_NUMERIC_ID = re.compile(r"^\d+$")
_UUID_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX_ID = re.compile(r"^[0-9a-fA-F]{16,}$")

# An email address in a path segment is personal data rather than an identifier worth
# keeping. APIs accept one as a lookup key (Checkout.com's `/customers/{identifier}` takes
# either a customer id or an address), and percent-encoding does not redact it, so a
# recorded request would otherwise carry the address into job logs and captured samples.
# Masking here rather than at each call site means a source that adds such a lookup later
# is covered without knowing to ask. Requires a dot-suffixed domain after the `@` so that
# non-email uses of `@` in a path (an `image@sha256:...` digest) stay readable.
_EMAIL_SEGMENT = re.compile(r"^[^/]*(?:@|%40)[^/]*\.[A-Za-z]{2,}$", re.IGNORECASE)
_EMAIL_PLACEHOLDER: Final[str] = "{email}"


def _scrub_path(path: str) -> str:
    if "@" not in path and "%40" not in path.lower():
        return path
    return "/".join(_EMAIL_PLACEHOLDER if _EMAIL_SEGMENT.match(part) else part for part in path.split("/"))


def scrub_url(url: str) -> str:
    """Return `url` with auth-bearing query-param values and email path segments masked.

    Param names are matched case-insensitively against `_REDACT_PARAM_NAMES`, their values
    replaced by REDACTED. Order, encoding, and unrelated params are preserved. Path segments
    that look like an email address become `{email}` — see `_EMAIL_SEGMENT`.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    path = _scrub_path(parts.path)
    if not parts.query:
        # Round-trip through urlunsplit only when the path actually changed, so a URL with
        # nothing to scrub is returned byte-for-byte rather than normalized.
        if path == parts.path:
            return url
        return urlunsplit((parts.scheme, parts.netloc, path, "", parts.fragment))

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    scrubbed = [(name, _REDACTED if name.lower() in _REDACT_PARAM_NAMES else value) for name, value in pairs]
    new_query = urlencode(scrubbed, doseq=False)
    return urlunsplit((parts.scheme, parts.netloc, path, new_query, parts.fragment))


def url_template(url: str) -> str:
    """Return a low-cardinality version of `url` for log grouping.

    Segments that look like numeric IDs, UUIDs, or long hex tokens are
    replaced with `{id}`. The query string is dropped entirely (logs already
    capture the scrubbed full URL alongside).
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    segments = parts.path.split("/")
    rewritten = [_template_segment(s) for s in segments]
    return urlunsplit((parts.scheme, parts.netloc, "/".join(rewritten), "", ""))


def _template_segment(segment: str) -> str:
    if not segment:
        return segment
    # Logged alongside the scrubbed URL, so an address survives here if it isn't masked here too.
    if _EMAIL_SEGMENT.match(segment):
        return _EMAIL_PLACEHOLDER
    if _NUMERIC_ID.match(segment) or _UUID_ID.match(segment) or _HEX_ID.match(segment):
        return "{id}"
    return segment


def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc or "unknown"
    except Exception:
        return "unknown"
