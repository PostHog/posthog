"""The config fingerprint shared by the schedule reconciler and inline scans.

Both need "same config, same key", and they must agree on canonicalization: the reconciler compares its
fingerprint against the one stamped on a live Temporal schedule, so any drift in how a config is
serialized would re-reconcile every schedule once.

The two callers want different lengths. A schedule fingerprint is a change detector, so a collision
costs one skipped reconcile and 16 hex is plenty. An inline scan's key is an identity, so a collision
would silently merge two unrelated questions into one result set, and it uses the full digest.
"""

import json
import hashlib
from typing import Any

# Short enough to read in a schedule's memo, wide enough that config drift is what changes it.
SCHEDULE_FINGERPRINT_LENGTH = 16


def config_fingerprint(payload: dict[str, Any] | None, *, length: int | None = None) -> str:
    canonical = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return digest if length is None else digest[:length]
