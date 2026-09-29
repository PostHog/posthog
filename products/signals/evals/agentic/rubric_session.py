from __future__ import annotations

import os
import json
import fcntl
import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from posthog.dataclasses import frozen

from products.signals.backend.rubrics_schema import ScoutRubricCriterion


class SessionRubric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    scout_name: str = Field(min_length=1)
    generated_at: AwareDatetime
    criteria: list[ScoutRubricCriterion] = Field(min_length=1)
    canonical_references: dict[str, JsonValue]
    source: dict[str, JsonValue]
    generation: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        ids = [criterion.id for criterion in self.criteria]
        if len(ids) != len(set(ids)) or not any(criterion.enabled for criterion in self.criteria):
            raise ValueError("A session rubric needs unique criteria and at least one enabled criterion")
        return self


@frozen
class RubricSnapshot:
    document: SessionRubric
    path: Path
    sha256: str


class RubricSession:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, scout_name: str) -> Path:
        return self.directory / "rubrics" / (hashlib.sha256(scout_name.encode()).hexdigest() + ".json")

    async def get_or_create(self, scout_name: str, generate: Callable[[], Awaitable[SessionRubric]]) -> RubricSnapshot:
        path = self._path(scout_name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "r+") as lock:
            # Keep the lock across generation so concurrent commands cannot choose different rubrics.
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.1)
            try:
                expected_hash = lock.read().strip()
                if expected_hash and not path.exists():
                    raise ValueError("The pinned session rubric is missing; restore it or use a new session directory")
                if path.exists():
                    content = path.read_bytes()
                    actual_hash = hashlib.sha256(content).hexdigest()
                    if expected_hash and actual_hash != expected_hash:
                        raise ValueError("The pinned session rubric changed; use a new session directory")
                    document = SessionRubric.model_validate_json(content)
                else:
                    document = await generate()
                    if document.scout_name != scout_name:
                        raise ValueError("The generated rubric belongs to a different scout")
                    content = (document.model_dump_json(indent=2) + "\n").encode()
                    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                    try:
                        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(descriptor, "wb") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                        temporary.replace(path)
                    finally:
                        temporary.unlink(missing_ok=True)
                    actual_hash = hashlib.sha256(content).hexdigest()
                if document.scout_name != scout_name:
                    raise ValueError("The saved rubric belongs to a different scout")
                if not expected_hash:
                    lock.seek(0)
                    lock.write(actual_hash + "\n")
                    lock.truncate()
                    lock.flush()
                    os.fsync(lock.fileno())
                return RubricSnapshot(document=document, path=path, sha256=actual_hash)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def write_judgment(directory: Path, *, result: dict[str, JsonValue], rubric: RubricSnapshot) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"judgment-{uuid4().hex}.json"
    document = {**result, "session_rubric_sha256": rubric.sha256, "session_rubric_path": str(rubric.path)}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(document, output, indent=2)
        output.write("\n")
    return path
