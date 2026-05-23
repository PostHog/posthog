"""Adapter for Octolens webhook deliveries (https://octolens.com).

Octolens posts a JSON payload per mention. Field names have shifted historically
and aren't fully documented, so this adapter is intentionally forgiving:
unknown fields are kept in ``raw_payload`` for re-processing, and missing fields
fall back to safe defaults rather than raising.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from ...facade.contracts import CreateMentionInput
from ...facade.enums import MentionType, Platform, SourceKind

if TYPE_CHECKING:
    from ...models import MentionSource


# Maximum bytes we'll keep in ``raw_payload``. Octolens payloads are tiny in
# practice, but we still cap to keep Temporal/Celery args bounded.
_RAW_PAYLOAD_MAX_BYTES = 64 * 1024


# Mapping of Octolens platform strings to our Platform enum.
_PLATFORM_MAP: dict[str, str] = {
    "twitter": Platform.X.value,
    "x": Platform.X.value,
    "x.com": Platform.X.value,
    "linkedin": Platform.LINKEDIN.value,
    "reddit": Platform.REDDIT.value,
    "hacker_news": Platform.HACKER_NEWS.value,
    "hackernews": Platform.HACKER_NEWS.value,
    "hn": Platform.HACKER_NEWS.value,
    "github": Platform.GITHUB.value,
    "youtube": Platform.YOUTUBE.value,
    "bluesky": Platform.BLUESKY.value,
    "mastodon": Platform.MASTODON.value,
}


def _normalize_platform(value: Any) -> str:
    if not isinstance(value, str):
        return Platform.OTHER.value
    return _PLATFORM_MAP.get(value.lower().strip(), Platform.OTHER.value)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    # Accept "2026-01-01T00:00:00Z" and similar ISO-8601 forms.
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _pick(d: dict, *keys: str, default: Any = "") -> Any:
    """Return the first present value in ``d`` for any of ``keys``."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _truncate_payload(payload: dict) -> dict:
    """Drop payload if it exceeds our raw-payload size cap. We keep an empty
    dict rather than failing the whole ingest — the dedup key + content is in
    other columns already."""
    import json

    try:
        if len(json.dumps(payload, default=str)) > _RAW_PAYLOAD_MAX_BYTES:
            return {"_truncated": True}
    except (TypeError, ValueError):
        return {"_truncated": True}
    return payload


def _author_block(d: dict) -> dict:
    """Octolens nests author info under ``author`` in some payloads and
    flattens it in others. Reduce to a single dict so we can index uniformly."""
    nested = d.get("author")
    if isinstance(nested, dict):
        return nested
    return {
        "name": d.get("author_name"),
        "handle": d.get("author_handle") or d.get("author_username"),
        "profile_url": d.get("author_url") or d.get("author_profile_url"),
        "followers": d.get("author_followers"),
    }


def _to_input(item: dict, source: "MentionSource") -> CreateMentionInput | None:
    """Normalize a single Octolens mention dict. Returns None if no usable
    external id is present (we cannot dedup without it)."""
    external_id = str(_pick(item, "id", "mention_id", "external_id", default="")).strip()
    if not external_id:
        return None

    author = _author_block(item)
    posted_at = _parse_datetime(
        _pick(item, "posted_at", "created_at", "timestamp", default="")
    )

    return CreateMentionInput(
        team_id=source.team_id,
        source_id=source.id,
        platform=_normalize_platform(_pick(item, "platform", "source", "network")),
        mention_type=MentionType.POST.value,
        external_id=external_id,
        url=str(_pick(item, "url", "link", "permalink", default="")),
        content=str(_pick(item, "content", "body", "text", "title", default="")),
        language=str(_pick(item, "language", "lang", default="")),
        author_handle=str(_pick(author, "handle", "username", default="")),
        author_display_name=str(_pick(author, "name", "display_name", default="")),
        author_profile_url=str(_pick(author, "profile_url", "url", default="")),
        author_followers=_coerce_int(_pick(author, "followers", "follower_count", default=None)),
        posted_at=posted_at,
        engagement=item.get("engagement") if isinstance(item.get("engagement"), dict) else {},
        raw_payload=_truncate_payload(item),
    )


class OctolensAdapter:
    """WebhookAdapter for Octolens deliveries.

    Octolens currently delivers either a single mention object as the root, or
    a ``{"mentions": [...]}`` envelope. Both shapes are accepted here.
    """

    kind: ClassVar[str] = SourceKind.OCTOLENS.value

    def to_create_inputs(
        self,
        payload: dict,
        source: "MentionSource",
    ) -> list[CreateMentionInput]:
        items = self._extract_items(payload)
        return [inp for item in items if (inp := _to_input(item, source)) is not None]

    @staticmethod
    def _extract_items(payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("mentions", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # Single mention as the root object
        return [payload]
