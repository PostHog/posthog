from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .stage import Stage, StageContext, clear_stage, execute_stage, is_current
from .steps.build_clone_links import BuildCloneLinks
from .steps.build_cut_surface import BuildCutSurface
from .steps.build_engine import BuildEngine
from .steps.build_groupjoin_surface import BuildGroupJoinSurface
from .steps.build_pair_surface import BuildPairSurface
from .steps.build_shuffler_curriculum import BuildShufflerCurriculum
from .steps.build_shuffler_substrate import BuildShufflerSubstrate
from .steps.clean_corpus import CleanCorpus
from .steps.enrich_concerns import EnrichConcerns
from .steps.evaluate import Evaluate
from .steps.harvest_groupjoin import HarvestGroupJoin
from .steps.import_export import ImportExport
from .steps.materialize_corpora import MaterializeCorpora
from .steps.normalize_label_ledgers import NormalizeLabelLedgers
from .steps.package import Package
from .steps.prepare_labels import PrepareLabels
from .steps.select_label_candidates import SelectLabelCandidates
from .steps.split_territories import SplitTerritories
from .steps.train_groupjoin import TrainGroupJoin
from .steps.train_pair import TrainPair
from .steps.train_shuffler import TrainShuffler
from .steps.train_split_gate import TrainSplitGate
from .steps.validate_inputs import ValidateInputs


def stages() -> list[Stage]:
    return [
        ImportExport(),
        EnrichConcerns(),
        BuildCloneLinks(),
        SelectLabelCandidates(),
        NormalizeLabelLedgers(),
        ValidateInputs(),
        CleanCorpus(),
        SplitTerritories(),
        PrepareLabels(),
        MaterializeCorpora(),
        BuildEngine(),
        BuildPairSurface(),
        TrainPair(),
        HarvestGroupJoin(),
        BuildGroupJoinSurface(),
        TrainGroupJoin(),
        BuildCutSurface(),
        TrainSplitGate(),
        BuildShufflerCurriculum(),
        BuildShufflerSubstrate(),
        TrainShuffler(),
        Evaluate("validation_a", "evaluate_a", requires_permission=False),
        Package(),
        Evaluate("validation_b", "evaluate_b", requires_permission=True),
    ]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Prepare labels, train, evaluate, and package the Signals pipeline")
    result.add_argument("config", type=Path)
    result.add_argument("--from", dest="from_stage")
    result.add_argument("--to", dest="to_stage", default="package")
    result.add_argument("--force", action="append", default=[], metavar="STAGE")
    result.add_argument("--plan", action="store_true")
    result.add_argument("--allow-validation-b", action="store_true")
    return result


def main() -> None:
    arguments = parser().parse_args()
    config = load_config(arguments.config)
    pipeline = stages()
    positions = {stage.name: index for index, stage in enumerate(pipeline)}
    start_name = arguments.from_stage or pipeline[0].name
    for value in (start_name, arguments.to_stage, *arguments.force):
        if value not in positions:
            parser().error(f"unknown stage {value!r}; choose from {', '.join(positions)}")
    start = positions[start_name]
    end = positions[arguments.to_stage]
    if start > end:
        parser().error("--from must not come after --to")
    if end == positions["evaluate_b"] and not arguments.allow_validation_b:
        parser().error("evaluate_b requires --allow-validation-b")
    context = StageContext(config=config, allow_validation_b=arguments.allow_validation_b)
    config.workspace.mkdir(parents=True, exist_ok=True)

    forced_from = min((positions[name] for name in arguments.force), default=len(pipeline))
    plan_rows: list[dict[str, object]] = []
    for index, stage in enumerate(pipeline):
        current = is_current(stage, context)
        selected = start <= index <= end
        forced = selected and index >= forced_from
        plan_rows.append(
            {
                "stage": stage.name,
                "selected": selected,
                "state": "forced" if forced else "current" if current else "stale_or_missing",
            }
        )
    if arguments.plan:
        print(json.dumps(plan_rows, indent=2))
        return

    for stage in pipeline[:start]:
        if not is_current(stage, context):
            raise RuntimeError(
                f"prerequisite {stage.name} is stale or missing; start at or before that stage instead of {start_name}"
            )
    for index in range(start, end + 1):
        stage = pipeline[index]
        forced = index >= forced_from
        if not forced and is_current(stage, context):
            print(f"[{index + 1}/{len(pipeline)}] {stage.name}: current", flush=True)
            continue
        clear_stage(stage, context)
        print(f"[{index + 1}/{len(pipeline)}] {stage.name}: running", flush=True)
        execute_stage(stage, context)
        print(f"[{index + 1}/{len(pipeline)}] {stage.name}: complete", flush=True)


if __name__ == "__main__":
    main()
