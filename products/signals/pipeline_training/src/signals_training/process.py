from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .io import JsonObject


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    cwd: str
    elapsed_seconds: float

    def as_json(self) -> JsonObject:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
        }


def deterministic_environment(seed: int) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": str(seed),
            "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return environment


def run_command(
    command: list[str],
    *,
    cwd: Path,
    seed: int,
    log_path: Path,
    extra_environment: dict[str, str] | None = None,
) -> CommandResult:
    environment = deterministic_environment(seed)
    if extra_environment:
        environment.update(extra_environment)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("ab") as log:
        log.write(("$ " + " ".join(command) + "\n").encode())
        subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    return CommandResult(command=command, cwd=str(cwd), elapsed_seconds=time.monotonic() - started)
