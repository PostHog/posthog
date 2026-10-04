from __future__ import annotations

import json
import hashlib
from collections import Counter
from typing import Literal, NoReturn, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from products.signals.backend.rubrics_judging import TrialEvidenceSource

EvidenceKind = Literal["instructions", "context", "summary", "report", "memory", "trace"]


class OfflineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["scout-offline-evidence-v1"] = "scout-offline-evidence-v1"
    sources: list[TrialEvidenceSource]
    source_locations: dict[str, list[str]]
    output_sha256: str
    transcript_sha256: str | None
    limitations: list[str]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_value(value: object) -> JsonValue:
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_value(child) for child in value]
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise ValueError("Saved evidence must contain only JSON values and string object keys.")


def _child(location: str, key: str | int) -> str:
    return f"{location}/{str(key).replace('~', '~0').replace('/', '~1')}"


def _render(value: JsonValue) -> str:
    if isinstance(value, str):
        # Literal values remain quotable without copying another layer of JSON escaping.
        encoded = json.dumps(value, ensure_ascii=False)
        if encoded[1:-1] == value:
            return encoded
        return f"string[{len(value)}]: {value}"
    if isinstance(value, dict):
        return (
            "{\n"
            + "\n".join(f"{json.dumps(key, ensure_ascii=False)}: {_render(value[key])}" for key in sorted(value))
            + "\n}"
        )
    if isinstance(value, list):
        return "[\n" + "\n".join(_render(child) for child in value) + "\n]"
    return _canonical_json(value)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The captured JSON contains duplicate object keys.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("The captured JSON contains a non-finite number.")


def _long_strings(value: JsonValue) -> list[str]:
    if isinstance(value, str):
        return [value] if len(value) >= 4096 else []
    if isinstance(value, dict):
        return [text for child in value.values() for text in _long_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _long_strings(child)]
    return []


def _transcript_instruction_locations(entry: JsonValue, location: str) -> set[str]:
    if not isinstance(entry, dict) or not isinstance(notification := entry.get("notification"), dict):
        return set()
    params = notification.get("params")
    if not isinstance(params, dict):
        return set()
    base = f"{location}/notification/params"
    match notification.get("method"):
        case "session/new":
            metadata = params.get("_meta")
            if isinstance(metadata, dict) and "systemPrompt" in metadata:
                return {f"{base}/_meta/systemPrompt"}
        case "session/prompt":
            if "prompt" in params:
                return {f"{base}/prompt"}
        case "session/update":
            update = params.get("update")
            if isinstance(update, dict) and update.get("sessionUpdate") == "user_message_chunk" and "content" in update:
                return {f"{base}/update/content"}
    return set()


class _EvidenceBuilder:
    def __init__(self) -> None:
        self.sources: dict[str, TrialEvidenceSource] = {}
        self.locations: dict[str, list[str]] = {}
        self.instructions: set[str] = set()
        self.shared_text: set[str] = set()
        self.transcript: list[JsonValue] | None = None
        self.transcript_sha256: str | None = None
        self.limitations = [
            "Sources retain the complete saved capture. The capture does not independently establish every action "
            "or external state; an absent action may be unobserved."
        ]

    def record(self, source_id: str, text: str, location: str, kind: EvidenceKind) -> None:
        if source_id not in self.sources:
            self.sources[source_id] = TrialEvidenceSource(id=source_id, kind=kind, text=text)
            self.locations[source_id] = []
        self.locations[source_id].append(location)

    def add_container(self, value: dict[str, JsonValue] | list[JsonValue], location: str, kind: EvidenceKind) -> None:
        shape = (
            {"type": "object", "keys": sorted(value)}
            if isinstance(value, dict)
            else {"type": "array", "length": len(value)}
        )
        self.record(
            f"offline-container-{_hash([kind, shape])[:32]}",
            f"Captured container shape: {_canonical_json(shape)}. Child values retain their original locations.",
            location,
            kind,
        )

    def add(self, value: JsonValue, location: str, kind: EvidenceKind) -> None:
        if location in self.instructions:
            kind = "instructions"
        split = any(instruction.startswith(f"{location}/") for instruction in self.instructions)
        if not isinstance(value, str):
            split = split or any(text in self.shared_text for text in _long_strings(value))
        if split:
            if isinstance(value, dict):
                self.add_container(value, location, kind)
                for key in sorted(value):
                    self.add(value[key], _child(location, key), kind)
                return
            if isinstance(value, list):
                self.add_container(value, location, kind)
                for index, child in enumerate(value):
                    self.add(child, _child(location, index), kind)
                return
        source_id = f"offline-{_hash([kind, value])[:32]}"
        self.record(source_id, _render(value), location, kind)

    def prepare_transcript(self, value: JsonValue) -> None:
        if isinstance(value, str) and value.strip():
            try:
                entries = [
                    cast(JsonValue, json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                    for line in value.split("\n")
                    if line.strip()
                ]
                self.transcript_sha256 = _hash(entries)
                self.transcript = entries
            except (ValueError, UnicodeError):
                self.limitations.append(
                    "The log could not be decoded losslessly as JSONL; its full raw text is retained."
                )
        else:
            self.limitations.append("No nonempty text transcript was captured; the saved log value is retained.")

    def add_transcript(self, value: JsonValue) -> None:
        if self.transcript is not None:
            self.add_container(self.transcript, "transcript:", "trace")
            for index, entry in enumerate(self.transcript):
                location = f"transcript:/{index}"
                self.instructions.update(_transcript_instruction_locations(entry, location))
                self.add(entry, location, "trace")
        else:
            self.limitations.append(
                "Undecoded log content may include candidate instructions. It is retained as instructions evidence "
                "because execution evidence cannot be separated safely."
            )
            self.add(value, "output:/raw_log", "instructions")

    def add_state(self, value: JsonValue, location: str) -> None:
        if not isinstance(value, dict) or not value:
            self.add(value, location, "context")
            return
        self.add_container(value, location, "context")
        for collection, rows in sorted(value.items()):
            collection_location = _child(location, collection)
            kind: EvidenceKind = "context"
            if collection in {"reports", "report_artefacts"}:
                kind = "report"
            elif collection == "scratchpad":
                kind = "memory"
            if isinstance(rows, list) and rows:
                self.add_container(rows, collection_location, kind)
                for index, row in enumerate(rows):
                    row_location = _child(collection_location, index)
                    if collection == "scout_runs" and isinstance(row, dict):
                        metadata = row.get("metadata")
                        if isinstance(metadata, dict) and "run_note" in metadata:
                            self.instructions.add(f"{row_location}/metadata/run_note")
                    self.add(row, row_location, kind)
            else:
                self.add(rows, collection_location, kind)

    def add_artifacts(self, value: JsonValue) -> None:
        if not isinstance(value, dict) or not value:
            self.add(value, "output:/artifacts", "context")
            return
        self.add_container(value, "output:/artifacts", "context")
        for key, child in sorted(value.items()):
            location = _child("output:/artifacts", key)
            if key in {"before", "after"}:
                self.add_state(child, location)
            else:
                if key == "requested" and isinstance(child, dict) and "run_note" in child:
                    self.instructions.add(f"{location}/run_note")
                self.add(child, location, "context")

    def build(self, output: dict[str, JsonValue]) -> OfflineEvidence:
        self.add_container(output, "output:", "context")
        self.instructions.update(f"output:/{key}" for key in ("prompt", "instructions", "run_note") if key in output)
        if "raw_log" in output:
            self.prepare_transcript(output["raw_log"])
        counts = Counter(_long_strings(output))
        if self.transcript is not None:
            counts.update(_long_strings(self.transcript))
        self.shared_text = {text for text, count in counts.items() if count > 1}
        for key, value in sorted(output.items()):
            if key == "raw_log":
                self.add_transcript(value)
            elif key == "artifacts":
                self.add_artifacts(value)
            else:
                kind: EvidenceKind = "summary" if key in {"summary", "last_message"} else "context"
                self.add(value, _child("output:", key), kind)
        if "raw_log" not in output:
            self.limitations.append("The saved output has no raw_log field; execution trace evidence is unavailable.")
        sources = [
            source.model_copy(
                update={
                    "text": "Original locations: " + json.dumps(sorted(self.locations[source_id])) + "\n" + source.text
                }
            )
            for source_id, source in self.sources.items()
        ]
        return OfflineEvidence(
            sources=sources,
            source_locations={source_id: sorted(locations) for source_id, locations in sorted(self.locations.items())},
            output_sha256=_hash(output),
            transcript_sha256=self.transcript_sha256,
            limitations=self.limitations,
        )


def build_offline_evidence(output: dict[str, object]) -> OfflineEvidence:
    value = _json_value(output)
    assert isinstance(value, dict)
    return _EvidenceBuilder().build(value)
