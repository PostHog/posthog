"""Ask Replay Vision a labeling question through the scanner type that answers it the way the labeler did.

A yes/no question and a question that marks moments run as a monitor, whose verdict is the presence and
whose citations are the moments. A choice question runs as a classifier over the option labels. A rating
question runs one scorer per option, since a scorer returns one score. Each scan's output then becomes a
comparable answer in the same shape as a labeler's (see `labels.py`).
"""

from typing import Any

from posthog.dataclasses import frozen

from products.replay_vision.backend.benchmark.labels import Question
from products.replay_vision.backend.models.replay_scanner import ScannerProvider, ScannerType
from products.replay_vision.backend.temporal.snapshots import ScannerSnapshot

# The key of the one scan a question runs when it is not split per option.
WHOLE_QUESTION = ""


@frozen
class ScanRequest:
    key: str
    snapshot: ScannerSnapshot


def scan_requests(question: Question, model: str) -> list[ScanRequest]:
    """The scans that answer `question`, or none when it has no comparable answer or cannot be asked."""
    prompt = _prompt(question)
    kind = question.kind
    if kind in ("binary", "spans"):
        return [_request(question, WHOLE_QUESTION, ScannerType.MONITOR, {"prompt": prompt}, model)]
    if kind in ("choice", "ordinal", "multi"):
        labels = [str(option.get("label", "")) for option in question.options]
        # The classifier pins its vocabulary as an enum, so a blank or repeated label cannot be asked.
        if not labels or not all(labels) or len(set(labels)) != len(labels):
            return []
        config = {"prompt": prompt, "tags": labels, "multi_label": kind == "multi"}
        return [_request(question, WHOLE_QUESTION, ScannerType.CLASSIFIER, config, model)]
    if kind == "ratings" and question.scale_max >= 2:
        return [
            _request(
                question,
                str(option["optionId"]),
                ScannerType.SCORER,
                {
                    "prompt": f"{prompt}\n\nRate this option: {option.get('label', '')}",
                    "scale": {"min": 1, "max": question.scale_max},
                },
                model,
            )
            for option in question.options
            if option.get("optionId")
        ]
    return []


def answer_from_outputs(question: Question, outputs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The comparable answer the scans gave, keyed like `scan_requests`, or None when they gave none."""
    kind = question.kind
    if kind == "ratings":
        ratings = {
            key: min(max(round(output["score"]), 1), question.scale_max)
            for key, output in outputs.items()
            if isinstance(output.get("score"), int | float)
        }
        return {"ratings": ratings} if ratings else None
    output = outputs.get(WHOLE_QUESTION)
    if output is None:
        return None
    if kind in ("binary", "spans"):
        verdict = output.get("verdict")
        if verdict not in ("yes", "no"):
            return None
        if kind == "binary":
            return {"choice": verdict == "yes"}
        moments = [
            {"startMs": segment["timestamp_ms"], "endMs": segment["timestamp_ms"]}
            for segment in output.get("reasoning_segments") or []
            if segment.get("kind") == "chip"
        ]
        return {"present": verdict == "yes", "moments": moments if verdict == "yes" else []}
    if kind in ("choice", "ordinal", "multi"):
        labels = [str(option.get("label", "")) for option in question.options]
        indices = sorted({labels.index(tag) for tag in output.get("tags") or [] if tag in labels})
        if kind != "multi" and len(indices) != 1:
            return None
        return {"choiceIndices": indices}
    return None


def _prompt(question: Question) -> str:
    parts = [question.definition.get("prompt"), question.definition.get("description")]
    return "\n\n".join(str(part).strip() for part in parts if part and str(part).strip())


def _request(
    question: Question, key: str, scanner_type: ScannerType, config: dict[str, Any], model: str
) -> ScanRequest:
    snapshot = ScannerSnapshot(
        name=f"benchmark-{question.question_id}-v{question.version}",
        scanner_type=scanner_type,
        scanner_version=1,
        model=model,
        provider=ScannerProvider.GOOGLE,
        emits_signals=False,
        scanner_config=config,
    )
    return ScanRequest(key=key, snapshot=snapshot)
