from products.experiments.backend.facade.api import list_concluded_experiments
from products.experiments.backend.facade.contracts import ConcludedExperiment
from products.reaperhog.backend.facade.enums import NAMED_SCOPES, SCOPE_ALL, SCOPE_EXPERIMENTS, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.enrollment import FlagEnrollment, enrollment_evidence
from products.reaperhog.backend.logic.repo import ReferenceCount
from products.reaperhog.backend.logic.scouts.base import ScoutContext, flag_patterns


class ExperimentsScout:
    name = ScoutName.EXPERIMENTS

    def applies_to(self, scope: str) -> bool:
        return scope in (SCOPE_EXPERIMENTS, SCOPE_ALL) or scope not in NAMED_SCOPES

    def run(self, context: ScoutContext) -> list[Hit]:
        experiments = list_concluded_experiments(context.team_id)
        constant_by_key = {key: constant for constant, key in context.repo.frontend_flag_keys().items()}
        keys = sorted({experiment.feature_flag_key for experiment in experiments})
        references = context.repo.references_many({key: flag_patterns(key, constant_by_key.get(key)) for key in keys})
        enrollment = context.flag_enrollment
        hits: list[Hit] = []
        for experiment in experiments:
            reference = references[experiment.feature_flag_key]
            if not reference.files or not context.in_scope(reference.files):
                continue
            hits.append(classify_experiment(experiment, reference, enrollment.get(experiment.feature_flag_key)))
        return hits


def classify_experiment(
    experiment: ConcludedExperiment, reference: ReferenceCount, enrollment: FlagEnrollment | None = None
) -> Hit:
    plan = experiment.cleanup
    removed = ", ".join(f'"{key}"' for key in plan.remove_variants) or "the flag check"
    keep = f'keep "{plan.keep_variant}"' if plan.keep_variant else "decide the kept path per site"
    ended = experiment.end_date.date().isoformat()
    return Hit(
        scout=ScoutName.EXPERIMENTS,
        root_kind=RootKind.FLAG,
        root=experiment.feature_flag_key,
        files=list(reference.files),
        reference_count=reference.total,
        decisive=plan.confident,
        summary=f'Experiment "{experiment.name}" {experiment.conclusion} on {ended}; {keep}, remove {removed}',
        evidence={
            "experiment_id": experiment.id,
            "experiment_name": experiment.name,
            "conclusion": experiment.conclusion,
            "end_date": experiment.end_date.isoformat(),
            "archived": experiment.archived,
            "keep_variant": plan.keep_variant,
            "remove_variants": ", ".join(plan.remove_variants),
            "cleanup_confident": plan.confident,
            "cleanup_rationale": plan.rationale,
            "cleanup_task_id": str(experiment.flag_cleanup_task_id) if experiment.flag_cleanup_task_id else None,
            "variants": ", ".join(experiment.variant_keys),
            **enrollment_evidence(enrollment),
            "code_files": len(reference.code_files),
            "test_files": len(reference.files) - len(reference.code_files),
            "references": reference.total,
        },
    )
