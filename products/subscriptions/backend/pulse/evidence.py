"""Safe serialization primitives for subscription-owned Pulse evidence."""

import json
from hashlib import sha256

MAX_RAW_EVIDENCE_BYTES = 64 * 1024


class EvidencePayloadTooLarge(ValueError):
    pass


def serialize_evidence_payload(payload: object) -> str:
    """Return a canonical, bounded payload suitable for encrypted short-lived storage."""
    try:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Evidence payload must be JSON serializable") from exc
    if len(serialized.encode("utf-8")) > MAX_RAW_EVIDENCE_BYTES:
        raise EvidencePayloadTooLarge("Evidence payload must be stored by reference")
    return serialized


def evidence_payload_ref(payload: object) -> str:
    """Return a stable metadata-only reference without exposing payload content."""
    return f"sha256:{sha256(serialize_evidence_payload(payload).encode()).hexdigest()}"
