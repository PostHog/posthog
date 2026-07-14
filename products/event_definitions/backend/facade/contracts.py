from dataclasses import dataclass


@dataclass(frozen=True)
class PlaceholderEventDefinition:
    name: str
    description: str | None = None
