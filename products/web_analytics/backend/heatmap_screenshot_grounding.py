"""Ground heatmap hot-spot coordinates against an actual page screenshot.

A heatmap report says "4 rage clicks at x≈0.83, y≈600px" — meaningless without seeing what sits there.
This module reuses a cached heatmap *screenshot* (a rendered page image), draws numbered markers at the hot
coordinates, and asks a vision model what UI element each marker lands on, so the tool can report "rage clicks
on the disabled Start trial button" instead of raw coordinates.

Reuse-only: it never renders a fresh screenshot (that's a slow async Browserless job) — if no cached
screenshot exists for the page, grounding is skipped and the caller degrades to the plain report.
"""

import io
import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from langchain_core.messages import HumanMessage
from PIL import Image, ImageDraw, ImageFont

from posthog.sync import database_sync_to_async

from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap

from ee.hogai.llm import MaxChatAnthropic

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

_GROUNDING_MODEL = "claude-haiku-4-5"
_MAX_MARKERS_PER_KIND = 5
_MAX_IMAGE_EDGE = 1568
_PREFERRED_WIDTH = 1024


@dataclass(frozen=True)
class _Marker:
    n: int
    kind: str
    rel_x: float
    y: int
    count: int


@dataclass(frozen=True)
class GroundingResult:
    """What the tool embeds: model-written descriptions of what sits under each marker, plus the annotated
    image (base64 JPEG), when the screenshot was captured, and the marker legend for the UI widget."""

    grounded_text: str
    annotated_image_b64: str
    markers: list[dict[str, object]]
    screenshot_captured_at: str


_MAX_CANDIDATE_SNAPSHOTS = 16


def _fetch_screenshot_bytes(team: "Team", page_url: str) -> tuple[bytes, datetime] | None:
    """Newest completed cached screenshot for the page (reuse-only). Returns (jpeg_bytes, captured_at) or None.

    URL match mirrors the heatmap query's trailing-slash tolerance. Only snapshots with inline `content`
    bytes are usable — `content_location` (object storage) isn't wired for reads yet — so a newer
    content-less screenshot must not mask an older usable one.
    """
    candidate_urls = list(dict.fromkeys([page_url, page_url.rstrip("/"), page_url.rstrip("/") + "/"]))
    ready = [
        snap
        for snap in HeatmapSnapshot.objects.filter(
            heatmap__team_id=team.id,
            heatmap__deleted=False,
            heatmap__type=SavedHeatmap.Type.SCREENSHOT,
            heatmap__status=SavedHeatmap.Status.COMPLETED,
            heatmap__url__in=candidate_urls,
            content__isnull=False,
        )
        .select_related("heatmap")
        .order_by("-heatmap__created_at")[:_MAX_CANDIDATE_SNAPSHOTS]
        if snap.content
    ]
    if not ready:
        return None
    newest = [snap for snap in ready if snap.heatmap_id == ready[0].heatmap_id]
    snap = min(newest, key=lambda s: abs(s.width - _PREFERRED_WIDTH))
    content = snap.content
    assert content is not None
    return bytes(content), snap.heatmap.created_at


def _build_markers(heatmap_data: Mapping[str, object]) -> list[_Marker]:
    """Top rage clusters then top click hotspots, numbered 1..k. Rage first — it's the priority signal."""
    markers: list[_Marker] = []
    n = 1
    for kind, key in (("rage", "rageclicks"), ("click", "clicks")):
        points = heatmap_data.get(key)
        if not isinstance(points, list):
            continue
        for p in points[:_MAX_MARKERS_PER_KIND]:
            if not isinstance(p, dict) or not p.get("count") or "pointer_relative_x" not in p or "pointer_y" not in p:
                continue
            markers.append(
                _Marker(
                    n=n,
                    kind=kind,
                    rel_x=float(p["pointer_relative_x"]),
                    y=int(p["pointer_y"]),
                    count=int(p["count"]),
                )
            )
            n += 1
    return markers


def _annotate(image_bytes: bytes, markers: list[_Marker]) -> bytes:
    """Draw numbered dots at each marker (rage = red, click = blue), then downscale. Coordinate mapping mirrors
    the frontend heatmap overlay: pixel_x = rel_x * width, pixel_y = pointer_y (already document pixels)."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)
    radius = max(16, width // 55)
    font = ImageFont.load_default(size=max(14, int(radius * 1.1)))
    for m in markers:
        px = min(max(int(m.rel_x * width), radius), width - radius)
        py = min(max(m.y, radius), height - radius)
        fill = (220, 38, 38) if m.kind == "rage" else (37, 99, 235)
        draw.ellipse([px - radius, py - radius, px + radius, py + radius], fill=fill, outline=(255, 255, 255), width=3)
        draw.text((px, py), str(m.n), fill=(255, 255, 255), anchor="mm", font=font)

    longest = max(img.size)
    if longest > _MAX_IMAGE_EDGE:
        scale = _MAX_IMAGE_EDGE / longest
        img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _prepare(
    team: "Team", page_url: str, heatmap_data: Mapping[str, object]
) -> tuple[bytes, list[_Marker], datetime] | None:
    """Sync half: fetch the screenshot and annotate it. None when there's nothing to ground."""
    markers = _build_markers(heatmap_data)
    if not markers:
        return None
    fetched = _fetch_screenshot_bytes(team, page_url)
    if fetched is None:
        return None
    image_bytes, captured_at = fetched
    return _annotate(image_bytes, markers), markers, captured_at


def _legend(markers: list[_Marker]) -> str:
    return "\n".join(f"#{m.n}: {m.kind}-click hot spot ({m.count}× interactions)" for m in markers)


_GROUNDING_PROMPT = (
    "This is a screenshot of the web page {url}. Numbered dots mark where users interact most — "
    "red dots are rage clicks (repeated frustrated clicking), blue dots are ordinary click hot spots:\n"
    "{legend}\n\n"
    "For each numbered marker, state concisely what UI element sits directly under it — its type (button, "
    "link, plain text, image, input, icon, empty space, etc.) and its visible label if any. Flag when a "
    "marker lands on something that is NOT interactive (users clicking dead space or a looks-clickable "
    "non-control is a key finding). Reply as a plain list, one line per marker: `#N: <element> — <note>`. "
    "Describe only what is visibly in the image; do not guess."
)


async def _ground(b64: str, markers: list[_Marker], page_url: str, team: "Team", user: "User") -> str | None:
    prompt = _GROUNDING_PROMPT.format(url=page_url, legend=_legend(markers))
    model = MaxChatAnthropic(
        model=_GROUNDING_MODEL,
        streaming=False,
        disable_streaming=True,
        stream_usage=False,
        max_tokens=800,
        user=user,
        team=team,
        billable=True,
        inject_context=False,
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]
    )
    response = await model.ainvoke([message])
    content = response.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = content.strip() if isinstance(content, str) else ""
    return text or None


async def ground_heatmap_hotspots(
    team: "Team", user: "User", *, page_url: str, heatmap_data: dict[str, object]
) -> GroundingResult | None:
    """Best-effort screenshot grounding of the page's hot spots. Returns None (never raises) whenever there's
    no cached screenshot, no hot spots, or any step fails — the caller degrades to the plain report."""
    try:
        prepared = await database_sync_to_async(_prepare)(team, page_url, heatmap_data)
        if prepared is None:
            return None
        annotated, markers, captured_at = prepared
        b64 = base64.b64encode(annotated).decode("ascii")
        grounded_text = await _ground(b64, markers, page_url, team, user)
    except Exception:
        logger.warning("heatmap_grounding.failed", team_id=team.id, exc_info=True)
        return None
    if not grounded_text:
        return None
    return GroundingResult(
        grounded_text=grounded_text,
        annotated_image_b64=b64,
        markers=[{"n": m.n, "kind": m.kind, "rel_x": m.rel_x, "y": m.y, "count": m.count} for m in markers],
        screenshot_captured_at=captured_at.date().isoformat(),
    )
