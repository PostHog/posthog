"""Per-source steering for the shared emission pipeline.

Teams steer the actionability gate through two keys on ``SignalSourceConfig.config``:

- ``steering`` (string): the team's plain-language preferences about this source's
  records (what matters, what to skip, what's out of scope). The actionability gate is
  the first consumer; the semantics are deliberately stage-agnostic so future pipeline
  stages can read the same text.
- ``default_not_actionable`` (bool): flips the gate's posture from "keep everything
  except what the rules exclude" to "only keep what clearly qualifies".

Teams supply rules, never prompt text: the canonical prompt scaffolding stays
upstream-owned, and the one-word output contract the gate parses is preserved. Steering
text is injected into the prompt *template* with braces escaped, so hostile input
(format-string syntax, stray braces) cannot make the later ``.format(description=...)``
raise and trip the gate's fail-open path.
"""

from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.contracts import DEFAULT_NOT_ACTIONABLE_KEY, STEERING_KEY, STEERING_MAX_LENGTH
from products.signals.backend.models import SignalSourceConfig

# Every canonical actionability prompt states its lenient posture on a line starting with
# this marker; the posture flip and the steering block anchor on it.
_POSTURE_MARKER = "When in doubt, classify as ACTIONABLE"
# Must stand alone: `default_not_actionable` is valid without steering text, so this line
# references the prompt's own ACTIONABLE criteria rather than a preferences block that may
# not be present.
_ALLOWLIST_POSTURE_LINE = (
    "When in doubt, classify as NOT_ACTIONABLE. This team only wants records that clearly match "
    "the ACTIONABLE criteria above, so err on the side of filtering."
)
_RESPONSE_MARKER = "Respond with exactly one word"

_STEERING_PREAMBLE = (
    "The team that owns this source has written preferences about its records: what matters, what to "
    "skip, and what is out of scope. Apply them when classifying; where they conflict with the guidance "
    "above, the team's preferences win. They never change the required output format."
)


@frozen
class SourceSteering:
    text: str = ""
    default_not_actionable: bool = False

    @property
    def active(self) -> bool:
        return bool(self.text) or self.default_not_actionable


def steering_from_config(config: Mapping[str, Any] | None) -> SourceSteering:
    """Parse a ``SignalSourceConfig.config`` blob into steering knobs.

    Defensive on purpose: the blob is API/MCP-writable JSON, and a malformed value must
    degrade to the canonical gate behavior rather than break emission.
    """
    if not isinstance(config, Mapping):
        return SourceSteering()
    raw_text = config.get(STEERING_KEY)
    text = raw_text.strip()[:STEERING_MAX_LENGTH] if isinstance(raw_text, str) else ""
    return SourceSteering(text=text, default_not_actionable=config.get(DEFAULT_NOT_ACTIONABLE_KEY) is True)


def apply_steering(prompt: str, steering: SourceSteering) -> str:
    """Inject a team's steering into an actionability prompt template.

    Returns the template unchanged when steering is inactive. Operates on the template
    (before ``.format(description=...)``) because that is the only string whose markers
    are trusted: after formatting, record content could itself contain the marker lines.
    Steering braces are doubled so the later format call renders them literally instead
    of raising and hitting the gate's assume-actionable failure path.
    """
    if not steering.active:
        return prompt

    lines = prompt.split("\n")
    marker_index = next((i for i, line in enumerate(lines) if line.startswith(_POSTURE_MARKER)), None)

    inserted: list[str] = []
    if steering.default_not_actionable:
        if marker_index is not None:
            lines[marker_index] = _ALLOWLIST_POSTURE_LINE
        else:
            inserted.append(_ALLOWLIST_POSTURE_LINE)
    if steering.text:
        escaped = steering.text.replace("{", "{{").replace("}", "}}")
        inserted.extend(["", _STEERING_PREAMBLE, "<team_preferences>", escaped, "</team_preferences>"])

    if not inserted:
        return "\n".join(lines)

    if marker_index is not None:
        insert_at = marker_index + 1
    else:
        # Custom prompt without the canonical posture line: keep the steering above the
        # output-contract instruction so the one-word contract stays last.
        response_index = next((i for i, line in enumerate(lines) if line.startswith(_RESPONSE_MARKER)), None)
        insert_at = response_index if response_index is not None else len(lines)
    return "\n".join(lines[:insert_at] + inserted + lines[insert_at:])


async def afetch_source_config(team_id: int, source_product: str, source_type: str) -> dict[str, Any]:
    """The team's ``SignalSourceConfig.config`` blob for one emission source, or ``{}``."""
    config = (
        await SignalSourceConfig.objects.filter(team_id=team_id, source_product=source_product, source_type=source_type)
        .values_list("config", flat=True)
        .afirst()
    )
    return config if isinstance(config, dict) else {}
