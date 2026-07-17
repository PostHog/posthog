from __future__ import annotations

import sys
from pathlib import Path

from .config import PipelineConfig
from .io import JsonObject, write_json
from .process import run_command
from .stage import StageContext

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def builder_script(name: str) -> Path:
    path = PROJECT_ROOT / "builders" / "models" / name
    if not path.is_file():
        raise FileNotFoundError(f"missing vendored builder: {path}")
    return path


def training_engine(context: StageContext) -> Path:
    del context
    return PROJECT_ROOT / "engine" / "target" / "release" / "signals-training-engine"


def python(context: StageContext) -> str:
    value = context.config.lineage.get("python")
    if not isinstance(value, str) or not value:
        raise ValueError("lineage.python must be a non-empty command")
    return sys.executable if value == "auto" else value


def run_logged(context: StageContext, stage: str, command: list[str], *, cwd: Path | None = None) -> None:
    result = run_command(
        command,
        cwd=cwd or context.config.root,
        seed=context.config.seed,
        log_path=context.log_path(stage),
    )
    context.commands.append(result)


def write_engine_config(path: Path, corpus: Path, **overrides: object) -> None:
    configuration: JsonObject = {
        "corpus_dir": str(corpus.resolve()),
        "mode": "classifier",
        "semantics": "sequential",
        "precompute_retrieval": True,
    }
    configuration.update(overrides)
    write_json(path, configuration)


def integer_setting(config: PipelineConfig, name: str) -> int:
    value = config.lineage.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"lineage.{name} must be an integer")
    return value


def number_setting(config: PipelineConfig, section: str, name: str) -> float:
    source = getattr(config, section)
    value = source.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{section}.{name} must be numeric")
    return float(value)


def string_setting(config: PipelineConfig, name: str) -> str:
    value = config.lineage.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"lineage.{name} must be a non-empty string")
    return value
