"""Whether a Slack request is polite enough to earn a heart reaction."""

import re

POLITE_REQUEST_REACTION = "orange_heart"

_POLITE_PHRASE = re.compile(r"\b(please|thank\s+you)\b", re.IGNORECASE)


def is_polite_request(text: str | None) -> bool:
    return bool(text and _POLITE_PHRASE.search(text))
