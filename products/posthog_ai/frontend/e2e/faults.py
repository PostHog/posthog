from __future__ import annotations

import time
import threading
from typing import Literal

from pydantic import JsonValue

FaultName = Literal["registration", "worker", "approval"]


class Fault:
    def __init__(self, name: FaultName, timeline: list[dict[str, JsonValue]]) -> None:
        self.name = name
        self.timeline = timeline
        self.condition = threading.Condition()
        self.armed = False
        self.released = False
        self.hits = 0
        self.target: str | None = None
        self.generations: list[int] = []
        self.released_generation = 0

    def record(self, event: str, **details: JsonValue) -> None:
        with self.condition:
            self.timeline.append({"time": time.monotonic(), "fault": self.name, "event": event, **details})
            self.condition.notify_all()

    def arm(self, target: str | None = None) -> None:
        with self.condition:
            if self.armed:
                raise ValueError(f"{self.name} already armed")
            self.armed = True
            self.released = False
            self.hits = 0
            self.generations.append(0)
            self.target = target
            self.record("armed", target=target)

    def reach(self, target: str | None = None) -> int | None:
        with self.condition:
            if not self.armed or self.released or (self.target is not None and self.target != target):
                return None
            self.hits += 1
            self.generations[-1] += 1
            if self.name == "approval" and self.target is None:
                self.target = target
            self.record("reached", target=target)
            return len(self.generations)

    def wait_until_reached(self) -> None:
        with self.condition:
            if not self.condition.wait_for(lambda: self.hits > 0, timeout=60):
                raise TimeoutError(f"Fault {self.name} was never reached")

    def wait_for_release(self, generation: int | None = None) -> None:
        with self.condition:
            generation = generation if generation is not None else len(self.generations)
            if not self.condition.wait_for(lambda: self.released_generation >= generation, timeout=90):
                raise TimeoutError(f"Fault {self.name} was not released")

    def release(self) -> None:
        with self.condition:
            self.released = True
            self.released_generation = len(self.generations)
            self.record("released")

    def reset(self) -> None:
        self.release()
        with self.condition:
            self.armed = False
            self.record("reset")

    def verify(self) -> None:
        if any(hits == 0 for hits in self.generations):
            raise AssertionError(f"Required fault {self.name} did not fire")
