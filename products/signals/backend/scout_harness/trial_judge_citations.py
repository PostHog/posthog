from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvidenceSource

_EXCERPT_CHARACTERS = 500
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class CitationReferenceError(ValueError):
    pass


class _CitationReference(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=100)
    excerpt_id: str = Field(min_length=1, max_length=100)


def _source_excerpts(text: str) -> dict[str, str]:
    excerpts: dict[str, str] = {}
    start = 0
    while start < len(text):
        end = min(start + _EXCERPT_CHARACTERS, len(text))
        if end < len(text):
            window = text[start:end]
            line_end = window.rfind("\n")
            if line_end >= 0:
                end = start + line_end + 1
            else:
                for offset in range(len(window) - 1, -1, -1):
                    if window[offset].isspace():
                        end = start + offset + 1
                        break
        excerpts[f"excerpt-{len(excerpts) + 1:04d}"] = text[start:end]
        start = end
    return excerpts


def _source_references(sources: list[TrialEvidenceSource]) -> dict[str, dict[str, str]]:
    references: dict[str, dict[str, str]] = {}
    for source in sources:
        if source.id in references:
            raise CitationReferenceError("The saved evidence contains duplicate source identifiers.")
        references[source.id] = _source_excerpts(source.text)
    return references


def build_citation_sources(sources: list[TrialEvidenceSource]) -> list[JsonValue]:
    references = _source_references(sources)
    rendered: list[JsonValue] = []
    for source in sources:
        excerpts: list[JsonValue] = [
            {"id": identifier, "text": text} for identifier, text in references[source.id].items()
        ]
        rendered.append({"id": source.id, "kind": source.kind, "excerpts": excerpts})
    return rendered


def resolve_citation_references(content: str, sources: list[TrialEvidenceSource]) -> str:
    try:
        document = _JSON_VALUE.validate_json(content, strict=True)
    except ValidationError:
        raise CitationReferenceError("The judge returned an invalid citation document.") from None
    if not isinstance(document, dict) or not isinstance(document.get("criteria"), list):
        raise CitationReferenceError("The judge returned an invalid citation document.")
    references = _source_references(sources)
    criteria = document["criteria"]
    assert isinstance(criteria, list)
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise CitationReferenceError("The judge returned an invalid citation document.")
        if "evidence" not in criterion:
            continue
        citations = criterion["evidence"]
        if not isinstance(citations, list):
            raise CitationReferenceError("The judge returned invalid evidence references.")
        resolved: list[JsonValue] = []
        for citation in citations:
            try:
                reference = _CitationReference.model_validate(citation)
            except ValidationError:
                raise CitationReferenceError("The judge returned an invalid evidence reference.") from None
            if not reference.source_id.strip() or not reference.excerpt_id.strip():
                raise CitationReferenceError("The judge returned a blank evidence reference.")
            source = references.get(reference.source_id)
            if source is None:
                raise CitationReferenceError("The judge cited an unknown evidence source.")
            quote = source.get(reference.excerpt_id)
            if quote is None:
                raise CitationReferenceError("The judge cited an unknown evidence excerpt.")
            if not quote.strip():
                raise CitationReferenceError("The judge cited a blank evidence excerpt.")
            resolved.append({"source_id": reference.source_id, "quote": quote})
        criterion["evidence"] = resolved
    return json.dumps(document, ensure_ascii=False)
