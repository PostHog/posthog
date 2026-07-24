from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class InputPaths(TypedDict):
    signals: Path
    reports: Path
    report_links: Path
    pair_labels: Path
    report_labels: Path
    operation_labels: Path


@dataclass(frozen=True)
class PipelineConfig:
    path: Path
    raw: dict[str, object]
    seed: int
    inputs: InputPaths
    source: dict[str, object]
    workspace: Path
    outputs: Path
    cleaning: dict[str, object]
    territories: dict[str, object]
    labeling: dict[str, object]
    lineage: dict[str, object]
    surfaces: dict[str, object]
    evaluation: dict[str, object]

    @property
    def root(self) -> Path:
        return self.path.parent

    def source_path(self, name: str) -> Path:
        value = self.source.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"source.{name} must be a non-empty path")
        return resolve_path(self.root, value)


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def object_field(raw: dict[str, object], name: str) -> dict[str, object]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, object], value)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _validate_output_layout(*, config_path: Path, source: dict[str, object], workspace: Path, outputs: Path) -> None:
    if _paths_overlap(workspace, outputs):
        raise ValueError("workspace and outputs must be separate, non-overlapping directories")
    for name, protected in (("project root", PROJECT_ROOT), ("configuration directory", config_path.parent)):
        if outputs == protected or protected.is_relative_to(outputs):
            raise ValueError(f"outputs must not replace or contain the {name}: {outputs}")

    source_names = ("export_directory", "concern_ledger", "llm_label_ledger", "human_label_ledger")
    for name in source_names:
        value = source.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"source.{name} must be a non-empty path")
        path = resolve_path(config_path.parent, value)
        protected = path if name == "export_directory" else path.parent
        if _paths_overlap(outputs, protected):
            raise ValueError(f"outputs must not overlap source.{name}: {outputs}")
    if config_path == outputs or config_path.is_relative_to(outputs):
        raise ValueError(f"outputs must not contain the configuration file: {outputs}")


def load_config(path: Path) -> PipelineConfig:
    config_path = path.expanduser().resolve()
    raw_value = json.loads(config_path.read_text())
    if not isinstance(raw_value, dict):
        raise ValueError("configuration root must be an object")
    raw = cast(dict[str, object], raw_value)
    if raw.get("schema_version") != 1:
        raise ValueError("configuration schema_version must be 1")
    seed = raw.get("seed")
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    workspace_value = raw.get("workspace")
    outputs_value = raw.get("outputs")
    if not isinstance(workspace_value, str) or not isinstance(outputs_value, str):
        raise ValueError("workspace and outputs must be paths")
    workspace = resolve_path(config_path.parent, workspace_value)
    outputs = resolve_path(config_path.parent, outputs_value)
    source = object_field(raw, "source")
    _validate_output_layout(config_path=config_path, source=source, workspace=workspace, outputs=outputs)
    inputs = InputPaths(
        signals=workspace / "enrich_concerns" / "signals.jsonl",
        reports=workspace / "import_export" / "reports.jsonl",
        report_links=workspace / "build_clone_links" / "report_links.jsonl",
        pair_labels=workspace / "normalize_label_ledgers" / "pairs.jsonl",
        report_labels=workspace / "normalize_label_ledgers" / "reports.jsonl",
        operation_labels=workspace / "normalize_label_ledgers" / "operations.jsonl",
    )
    return PipelineConfig(
        path=config_path,
        raw=raw,
        seed=seed,
        inputs=inputs,
        source=source,
        workspace=workspace,
        outputs=outputs,
        cleaning=object_field(raw, "cleaning"),
        territories=object_field(raw, "territories"),
        labeling=object_field(raw, "labeling"),
        lineage=object_field(raw, "lineage"),
        surfaces=object_field(raw, "surfaces"),
        evaluation=object_field(raw, "evaluation"),
    )
