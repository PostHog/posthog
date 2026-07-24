from __future__ import annotations

from pathlib import Path

from ..io import JsonObject, write_json
from ..lineage import run_logged, training_engine
from ..stage import StageContext


class BuildEngine:
    name = "build_engine"

    def input_paths(self, context: StageContext) -> list[Path]:
        root = training_engine(context).parents[2]
        return [root / "Cargo.toml", root / "Cargo.lock", root / "build.rs", root / "src"]

    def output_paths(self, context: StageContext) -> list[Path]:
        return [training_engine(context), context.stage_dir(self.name) / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"profile": "release", "features": ["neural-onnx"]}

    def run(self, context: StageContext) -> None:
        root = training_engine(context).parents[2]
        run_logged(
            context,
            self.name,
            ["cargo", "build", "--release", "--features", "neural-onnx"],
            cwd=root,
        )
        binary = training_engine(context)
        if not binary.is_file():
            raise RuntimeError(f"Cargo did not produce {binary}")
        write_json(
            context.stage_dir(self.name) / "summary.json",
            {
                "binary": str(binary),
                "profile": "release",
                "contract": "replay, pair/cut feature extraction, and frozen-label scoring",
            },
        )
