from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import platform
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path
from types import ModuleType
from typing import Protocol

from . import __version__
from .config import PipelineConfig
from .io import JsonObject, canonical_json, hash_paths, write_json
from .process import CommandResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCKED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==")


@dataclass
class StageContext:
    config: PipelineConfig
    allow_validation_b: bool
    commands: list[CommandResult] = field(default_factory=list)

    def stage_dir(self, name: str) -> Path:
        return self.config.workspace / name

    def log_path(self, name: str) -> Path:
        return self.stage_dir(name) / "stage.log"


class Stage(Protocol):
    name: str

    def input_paths(self, context: StageContext) -> list[Path]: ...

    def output_paths(self, context: StageContext) -> list[Path]: ...

    def config_fragment(self, context: StageContext) -> JsonObject: ...

    def run(self, context: StageContext) -> None: ...


def implementation_hash(stage: Stage) -> str:
    module = inspect.getmodule(stage.__class__)
    if not isinstance(module, ModuleType) or not module.__file__:
        raise RuntimeError(f"cannot locate implementation for {stage.name}")
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def project_source_hashes() -> dict[str, str]:
    paths = sorted(
        [
            PROJECT_ROOT / "pyproject.toml",
            PROJECT_ROOT / "requirements.lock",
            *Path(__file__).resolve().parent.rglob("*.py"),
            *(PROJECT_ROOT / "schemas").glob("*.json"),
        ],
        key=lambda path: path.relative_to(PROJECT_ROOT).as_posix(),
    )
    return hash_paths(paths)


def runtime_environment() -> JsonObject:
    packages: dict[str, str] = {}
    locked_packages = sorted(
        match.group(1)
        for line in (PROJECT_ROOT / "requirements.lock").read_text().splitlines()
        if (match := LOCKED_REQUIREMENT.match(line.strip()))
    )
    for name in locked_packages:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "missing"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
    }


@cache
def builder_source_hashes() -> dict[str, str]:
    builder_root = PROJECT_ROOT / "builders"
    paths = sorted(
        [*(builder_root / "models").rglob("*.py"), *(builder_root / "core").rglob("*.py")],
        key=lambda path: path.relative_to(builder_root).as_posix(),
    )
    return hash_paths(paths)


def stage_fingerprint(stage: Stage, context: StageContext) -> tuple[str, JsonObject]:
    payload: JsonObject = {
        "orchestrator_version": __version__,
        "stage": stage.name,
        "implementation_sha256": implementation_hash(stage),
        "project_sources": project_source_hashes(),
        "vendored_builder_sources": builder_source_hashes(),
        "runtime": runtime_environment(),
        "config": stage.config_fragment(context),
        "inputs": hash_paths(stage.input_paths(context)),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest(), payload


def manifest_path(stage: Stage, context: StageContext) -> Path:
    return context.stage_dir(stage.name) / "_stage.json"


def is_current(stage: Stage, context: StageContext) -> bool:
    path = manifest_path(stage, context)
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    fingerprint, _payload = stage_fingerprint(stage, context)
    if manifest.get("fingerprint") != fingerprint or manifest.get("status") != "complete":
        return False
    outputs = stage.output_paths(context)
    if any(not path.exists() for path in outputs):
        return False
    return manifest.get("outputs") == hash_paths(outputs)


def clear_stage(stage: Stage, context: StageContext) -> None:
    directory = context.stage_dir(stage.name)
    if directory.exists():
        shutil.rmtree(directory)


def execute_stage(stage: Stage, context: StageContext) -> None:
    directory = context.stage_dir(stage.name)
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint, payload = stage_fingerprint(stage, context)
    context.commands = []
    started = time.monotonic()
    try:
        stage.run(context)
        missing = [str(path) for path in stage.output_paths(context) if not path.exists()]
        if missing:
            raise RuntimeError(f"{stage.name} did not produce: {', '.join(missing)}")
        manifest: JsonObject = {
            **payload,
            "fingerprint": fingerprint,
            "status": "complete",
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "commands": [command.as_json() for command in context.commands],
            "outputs": hash_paths(stage.output_paths(context)),
        }
        write_json(manifest_path(stage, context), manifest)
    except BaseException as error:
        write_json(
            manifest_path(stage, context),
            {
                **payload,
                "fingerprint": fingerprint,
                "status": "failed",
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "commands": [command.as_json() for command in context.commands],
                "error": f"{type(error).__name__}: {error}",
            },
        )
        raise
