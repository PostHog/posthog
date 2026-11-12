"""Whether a Slack request is polite enough to earn a heart reaction."""

import re

POLITE_REQUEST_REACTION = "orange_heart"

_POLITE_PHRASE = re.compile(r"\b(please|thanks|thank\s+you)\b", re.IGNORECASE)


def is_polite_request(text: str) -> bool:
    return _POLITE_PHRASE.search(text) is not None
