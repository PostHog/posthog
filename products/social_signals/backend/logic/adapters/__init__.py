"""Webhook adapters for social_signals.

An adapter converts a source-specific webhook payload into one or more
normalized ``CreateMentionInput`` records. New ingestion sources drop in by
adding a new adapter class and registering it here.
"""

from ..errors import UnknownAdapterError
from .base import WebhookAdapter
from .octolens import OctolensAdapter

_REGISTRY: dict[str, type[WebhookAdapter]] = {
    OctolensAdapter.kind: OctolensAdapter,
}


def get_adapter(kind: str) -> WebhookAdapter:
    """Return an adapter instance for ``kind`` or raise UnknownAdapterError."""
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise UnknownAdapterError(f"No webhook adapter registered for kind={kind!r}")
    return cls()


__all__ = ["WebhookAdapter", "OctolensAdapter", "get_adapter"]
