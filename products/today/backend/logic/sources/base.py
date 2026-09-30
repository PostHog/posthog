"""The interface every briefing source implements."""

import abc
from typing import ClassVar

from ..candidates import Candidate, SourceContext


class Source(abc.ABC):
    """One place the briefing reads a person's items from.

    Each source runs as its own Temporal activity, so a slow or failing source costs only its own items.
    """

    # Stable id: the activity input, and the entry in `failed_sources` when the source fails.
    name: ClassVar[str]

    @abc.abstractmethod
    def collect(self, ctx: SourceContext) -> list[Candidate]:
        """The person's items from this source. Raise on failure; the caller records the source as failed."""
