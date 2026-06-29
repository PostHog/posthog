"""Interpret a team's session-replay masking config for the replay-vision scout.

The rasterized video the scout reasons over bakes in whatever the SDK masked at capture time, so a
heavily-masked recording shows the model redacted boxes — not what the user actually saw. The team's
live `session_recording_masking_config` (the same blob delivered to the SDK via RemoteConfig) is the
only server-side signal for how much was redacted, so we derive a human-readable summary from it to
either skip the session or warn the model.

Keys mirror the SDK / `posthog/api/team.py` validation: `maskAllInputs` (bool), `maskTextSelector`
(CSS selector, `"*"` masks all text), `blockSelector` (CSS selector for elements rendered as blanks).
"""

from typing import Any


def summarize_masking_config(masking_config: dict[str, Any] | None) -> tuple[str | None, bool]:
    """Return ``(human summary of what's redacted, is_fully_masked)`` for a team masking config.

    ``summary`` is ``None`` when the team has no explicit masking config or has explicitly disabled
    masking — the pre-existing behavior, left untouched. ``is_fully_masked`` is ``True`` only for the
    "total privacy" preset (``maskTextSelector == "*"``), where on-screen text is wholesale redacted
    and any vision finding would describe redaction rather than the session — the caller skips those.
    """
    config = masking_config or {}
    if not config:
        return None, False

    mask_text_selector = config.get("maskTextSelector")
    block_selector = config.get("blockSelector")
    mask_all_inputs = config.get("maskAllInputs")
    fully_masked = mask_text_selector == "*"

    parts: list[str] = []
    if mask_text_selector == "*":
        parts.append("all on-screen text is masked")
    elif mask_text_selector:
        parts.append(f"on-screen text matching the selector `{mask_text_selector}` is masked")
    if block_selector:
        parts.append(
            f"elements matching the selector `{block_selector}` are blocked out (rendered as blank placeholders)"
        )
    if mask_all_inputs:
        parts.append("text typed into input fields is masked")

    summary = "; ".join(parts) if parts else None
    return summary, fully_masked
