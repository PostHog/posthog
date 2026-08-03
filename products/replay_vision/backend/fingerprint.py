"""The config fingerprint shared by the schedule reconciler and ad-hoc scans.

Both need "same config → same short id", and they must agree on canonicalization: the reconciler
compares its fingerprint against the one stamped on a live Temporal schedule, so any drift in how a
config is serialized would re-reconcile every schedule once.
"""

import json
import hashlib
from typing import Any

# Enough hex that a collision between two distinct configs is implausible, short enough to read.
FINGERPRINT_LENGTH = 16


def config_fingerprint(payload: dict[str, Any] | None) -> str:
    canonical = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:FINGERPRINT_LENGTH]
