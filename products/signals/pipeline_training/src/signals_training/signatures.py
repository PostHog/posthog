from __future__ import annotations

import re

from .io import JsonObject

TOKEN = re.compile(r"[a-z0-9_$]+")


def tokens(value: object) -> list[str]:
    return sorted(set(TOKEN.findall(str(value).lower()))) if value else []


def signature_row(document_id: str, signature: JsonObject, embedding: list[object]) -> JsonObject:
    tags = signature.get("concern_tags", [])
    tag_values = tags if isinstance(tags, list) else []
    return {
        "document_id": document_id,
        "polarity": str(signature.get("polarity") or "neutral"),
        "surface": tokens(signature.get("surface")),
        "failmode": tokens(signature.get("failure_mode")),
        "tags": sorted({token for tag in tag_values for token in tokens(tag)}),
        "anchor": tokens(signature.get("error_anchor")),
        "oneliner": tokens(signature.get("one_liner")),
        "has_failmode": bool(signature.get("failure_mode")),
        "has_anchor": bool(signature.get("error_anchor")),
        "emb": embedding,
    }
