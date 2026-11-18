from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskRunLog:
    key: str
