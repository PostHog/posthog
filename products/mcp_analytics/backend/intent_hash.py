"""Content hash that joins `$mcp_tool_call` events to embedded intents and topic assignments.

Python and HogQL must hash the identical bytes: the raw, untruncated `$mcp_intent` text.
"""

import hashlib

INTENT_PROPERTY = "$mcp_intent"

# HogQL `sha256` expands to lower(hex(SHA256(x))), matching `intent_hash` below.
INTENT_HASH_HOGQL = f"sha256(toString(properties.{INTENT_PROPERTY}))"


def intent_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
