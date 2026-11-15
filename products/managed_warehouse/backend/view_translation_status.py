from __future__ import annotations

import json
import hashlib


def source_query_hash(query: object) -> str:
    serialized = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode()).hexdigest()
