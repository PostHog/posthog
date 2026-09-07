import re
from typing import TYPE_CHECKING, Any

from products.replay_vision.backend.models.replay_scanner import ScannerType

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_observation import ReplayObservation

EVENT_ID_CITATION_RE = re.compile(r"\(event_id [0-9a-f]{16}\)", re.IGNORECASE)

SEARCH_SNIPPET_LIMIT = 600


def read_output(obs: "ReplayObservation") -> dict[str, Any] | None:
    scanner_result = obs.scanner_result if isinstance(obs.scanner_result, dict) else None
    output = scanner_result.get("model_output") if scanner_result is not None else None
    return output if isinstance(output, dict) else None


def describe_output(output: dict[str, Any]) -> str | None:
    """Short type-specific descriptor (verdict / score / tags / title) prepended to each result line."""
    scanner_type = output.get("scanner_type")
    if scanner_type == ScannerType.MONITOR and output.get("verdict") is not None:
        return f"verdict={output['verdict']}"
    if scanner_type == ScannerType.SCORER and output.get("score") is not None:
        label = output.get("label")
        return f"score={output['score']}{f' ({label})' if label else ''}"
    if scanner_type == ScannerType.CLASSIFIER:
        tags = [*(output.get("tags") or []), *(output.get("tags_freeform") or [])]
        return f"tags={', '.join(str(t) for t in tags)}" if tags else None
    if scanner_type == ScannerType.SUMMARIZER:
        title = output.get("title")
        return str(title) if isinstance(title, str) and title.strip() else None
    return None


def explanation_text(output: dict[str, Any]) -> str:
    """The free text a scanner wrote about the session: monitors, scorers and classifiers reason, summarizers
    summarize. Event-id citations are for the UI, so they are stripped here."""
    explanation = output.get("reasoning") or output.get("summary")
    if not isinstance(explanation, str):
        return ""
    return re.sub(r"\s+", " ", EVENT_ID_CITATION_RE.sub("", explanation)).strip()


def format_line(obs: "ReplayObservation", output: dict[str, Any], *, show_scanner: bool) -> str:
    descriptor = describe_output(output)
    clean = explanation_text(output)[:SEARCH_SNIPPET_LIMIT]

    prefix = f"{obs.created_at:%Y-%m-%d}"
    session = str(obs.session_id)
    # `scanner_name` is annotated by the search hydration so no scanner row is joined; fall back to the relation.
    scanner_name = getattr(obs, "scanner_name", None) or (obs.scanner.name if show_scanner and obs.scanner else "")
    scanner_part = f" {scanner_name}" if show_scanner and scanner_name else ""
    descriptor_part = f" [{descriptor}]" if descriptor else ""
    return f"- (session {session}, {prefix}){scanner_part}{descriptor_part} {clean}".rstrip()
