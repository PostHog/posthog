"""Copies the images a provider hosts for an imported email into the team's email media library.

They stop loading once the team closes its account there. An image on any other host stays as it is.
"""

import re
import time
import bisect
from collections.abc import Callable, Iterable

from posthog.dataclasses import frozen

from products.workflows.backend.facade.api import can_edit_media
from products.workflows.backend.facade.contracts import EmailImageSource
from products.workflows.backend.facade.email_images import copy_images_for_team, is_hosted

MAX_IMAGES_PER_STEP = 1000
MAX_SECONDS_PER_PAGE = 10 * 60
# Copying time, not the provider's API. Past it, the step's later images keep their address. Without it a slow host could hold a step for days.
MAX_SECONDS_PER_STEP = 30 * 60
_MAX_NOTED_IMAGES = 10
_MAX_NOTED_URL_LENGTH = 300

# Every repeat is capped, so an unclosed quote can't make a scan slow. Regular expressions rather than a parser, because
# Outlook's VML sits inside comments and the rest of the HTML has to stay byte for byte as it was.
_ATTRIBUTE = re.compile(
    r"""(?<=[\s"'])(?:src|background|poster)\s{0,20}=\s{0,20}(?:"([^"]{0,8192})"|'([^']{0,8192})'|([^\s"'<>]{1,8192}))""",
    re.IGNORECASE,
)
_SRCSET = re.compile(
    r"""(?<=[\s"'])(?:srcset|imagesrcset)\s{0,20}=\s{0,20}(?:"([^"]{0,16384})"|'([^']{0,16384})'|([^\s"'<>]{1,8192}))""",
    re.IGNORECASE,
)
_SRCSET_URL = re.compile(r"(?:https?:)?//[^\s]+")
_CSS_URL = re.compile(
    r"""\burl\(\s{0,20}(?:"([^"]{0,8192})"|'([^']{0,8192})'|&(?:quot|apos|#0?34|#0?39|#x27);([^"'()<>]{0,8192}?)&(?:quot|apos|#0?34|#0?39|#x27);"""
    r"""|([^\s"'()<>]{1,8192}))\s{0,20}\)""",
    re.IGNORECASE,
)
# CSS is read only where a browser reads it, so a `url(...)` in a link or in the text stays as written.
_STYLE_ATTRIBUTE = re.compile(
    r"""(?<=[\s"'])style\s{0,20}=\s{0,20}(?:"([^"]{0,65536})"|'([^']{0,65536})')""", re.IGNORECASE
)
_STYLE_OPEN = re.compile(r"<style\b[^>]{0,1000}>", re.IGNORECASE)
_STYLE_CLOSE = re.compile(r"</style\s{0,20}>", re.IGNORECASE)
_AMPERSAND = re.compile(r"&(?:amp|#38|#x26);", re.IGNORECASE)
# Liquid, Handlebars, Mailchimp and Mailgun tags, written out or percent-encoded. The address only exists at send time.
_TEMPLATE_TAG = re.compile(r"[{}]|\*\||\|\*|%recipient|%7b|\*%7c", re.IGNORECASE)


@frozen
class PlacedImages:
    html: str
    # What still loads from the provider, for the person to fix.
    notes: tuple[str, ...] = ()


class TemplateImages:
    """The image copies of one attempt at an import step. Without a source it changes nothing."""

    def __init__(
        self,
        team_id: int = 0,
        user_id: int | None = None,
        source: EmailImageSource | None = None,
        can_upload: bool = False,
    ) -> None:
        self._team_id = team_id
        self._user_id = user_id
        self._source = source
        self._can_upload = can_upload
        self._copied: dict[str, str] = {}
        self._tried: set[str] = set()
        self._remaining = MAX_IMAGES_PER_STEP
        self._seconds_left: float = MAX_SECONDS_PER_STEP

    @property
    def enabled(self) -> bool:
        return self._source is not None

    def copy(self, bodies: Iterable[str]) -> None:
        """Copy the images `bodies` show, before the page that saves them, so no transaction waits for a download."""
        source, user_id = self._source, self._user_id
        if source is None or user_id is None or not self._can_upload:
            return
        # Past either limit nothing more is copied, so the addresses aren't kept either.
        if self._remaining <= 0 or self._seconds_left <= 0:
            return
        found: dict[str, None] = {}

        def collect(value: str) -> str:
            if (url := _hosted_url(value, source)) is not None and url not in self._tried:
                found[url] = None
            return value

        for body in bodies:
            _rewrite(body, collect)
        if not found:
            return
        # The run writes in the background, so the person who started it may have lost access since.
        if not can_edit_media(team_id=self._team_id, user_id=user_id):
            self._can_upload = False
            return
        now = time.monotonic()
        copied = copy_images_for_team(
            self._team_id,
            user_id,
            found,
            source,
            max_images=self._remaining,
            deadline=now + min(self._seconds_left, MAX_SECONDS_PER_PAGE),
        )
        self._copied.update(copied.copies)
        self._remaining -= copied.downloads
        self._seconds_left -= time.monotonic() - now
        self._tried.update(found)

    def place(self, html: str) -> PlacedImages:
        """`html` with every copied image at its copy, and notes on the ones that still load from the provider."""
        source = self._source
        if source is None:
            return PlacedImages(html=html)
        missed: dict[str, None] = {}
        tagged: dict[str, None] = {}

        def replace(value: str) -> str:
            url = _hosted_url(value, source)
            if url is None:
                if (tag := _TEMPLATE_TAG.search(value)) and _names_host(value, source):
                    # Up to the tag, because a quote inside Liquid can end the value in the middle of it.
                    tagged[f"{value[: tag.start()]}…"] = None
                return value
            if url in self._copied:
                return self._copied[url]
            missed[url] = None
            return value

        html = _rewrite(html, replace)
        notes: list[str] = []
        if missed and not self._can_upload:
            notes.append(
                f"{_count(len(missed))} from {source.label}'s servers, because this import can't write to the media "
                "library. The person importing needs editor access to it, and their API key or PostHog MCP connection "
                f"needs the uploaded_media:write scope. Upload {_named(missed)} before you close your {source.label} "
                "account."
            )
        elif missed:
            notes.append(
                f"{_count(len(missed))} from {source.label}'s servers, because PostHog couldn't copy "
                f"{'it' if len(missed) == 1 else 'them'}: {_named(missed)}. Upload "
                f"{'it' if len(missed) == 1 else 'them'} to the media library before you close your {source.label} "
                "account."
            )
        if tagged:
            notes.append(
                f"{_count(len(tagged))} from {source.label}'s servers, because the address holds a template tag: "
                f"{_named(tagged)}. Use an image from the media library there before you close your {source.label} account."
            )
        return PlacedImages(html=html, notes=tuple(notes))


def _hosted_url(value: str, source: EmailImageSource) -> str | None:
    """The https address of an image on the provider's hosts, or None. Older emails name those hosts over http."""
    if _TEMPLATE_TAG.search(value):
        return None
    url = _AMPERSAND.sub("&", value.strip())
    scheme, separator, rest = url.partition("//")
    if not separator or scheme.lower() not in ("", "http:", "https:"):
        return None
    url = f"https://{rest}"
    return url if is_hosted(url, source) else None


def _names_host(value: str, source: EmailImageSource) -> bool:
    lowered = value.lower()
    return any(f"//{host}/" in lowered for host in source.hosts) or any(
        f".{suffix}/" in lowered for suffix in source.host_suffixes
    )


def _rewrite(html: str, replace: Callable[[str], str]) -> str:
    """`html` with every image address run through `replace`. Links and text are left alone."""

    def in_value(match: re.Match[str]) -> str:
        return _with_value(match, replace)

    def in_srcset(match: re.Match[str]) -> str:
        return _with_value(match, lambda value: _SRCSET_URL.sub(_srcset_candidate, value))

    def _srcset_candidate(match: re.Match[str]) -> str:
        # A comma that ends a candidate isn't part of its address.
        url = match.group(0).rstrip(",")
        return replace(url) + match.group(0)[len(url) :]

    def in_css(css: str) -> str:
        return _CSS_URL.sub(in_value, css)

    html = _ATTRIBUTE.sub(in_value, html)
    html = _SRCSET.sub(in_srcset, html)
    html = _STYLE_ATTRIBUTE.sub(lambda match: _with_value(match, in_css), html)
    return _in_style_blocks(html, in_css)


def _in_style_blocks(html: str, replace: Callable[[str], str]) -> str:
    # The closing tags are found once, so many unclosed `<style>` tags can't make the scan slow.
    closes = [match.start() for match in _STYLE_CLOSE.finditer(html)]
    parts: list[str] = []
    position = 0
    for match in _STYLE_OPEN.finditer(html):
        if match.start() < position:
            continue
        index = bisect.bisect_left(closes, match.end())
        end = closes[index] if index < len(closes) else len(html)
        parts += [html[position : match.end()], replace(html[match.end() : end])]
        position = end
    parts.append(html[position:])
    return "".join(parts)


def _with_value(match: re.Match[str], replace: Callable[[str], str]) -> str:
    group = match.lastindex
    if group is None:
        return match.group(0)
    value = match.group(group)
    start, end = match.start(group) - match.start(), match.end(group) - match.start()
    replaced = replace(value)
    return match.group(0) if replaced == value else match.group(0)[:start] + replaced + match.group(0)[end:]


def _count(count: int) -> str:
    return "1 image still loads" if count == 1 else f"{count} images still load"


def _named(urls: Iterable[str]) -> str:
    # The addresses are the provider's text and go into the template's description, so each is kept short.
    listed = [" ".join(url.split())[:_MAX_NOTED_URL_LENGTH] for url in urls]
    more = f" and {len(listed) - _MAX_NOTED_IMAGES} more" if len(listed) > _MAX_NOTED_IMAGES else ""
    return f"{', '.join(listed[:_MAX_NOTED_IMAGES])}{more}"
