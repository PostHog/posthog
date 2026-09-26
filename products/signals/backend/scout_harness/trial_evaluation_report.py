from collections import Counter
from datetime import UTC, datetime
from statistics import mean

from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialComparisonReport,
    TrialCriterionAggregate,
    TrialCriterionVerdict,
    TrialEvaluationSnapshot,
    TrialRunJudgment,
    TrialVariantAggregate,
)


def _pass_rate(verdicts: list[TrialCriterionVerdict]) -> float | None:
    decisive = [verdict for verdict in verdicts if verdict.verdict in {"pass", "fail"}]
    return sum(verdict.verdict == "pass" for verdict in decisive) / len(decisive) if decisive else None


def _coverage(verdicts: list[TrialCriterionVerdict]) -> float | None:
    applicable = [verdict for verdict in verdicts if verdict.verdict != "not_applicable"]
    return sum(verdict.verdict in {"pass", "fail"} for verdict in applicable) / len(applicable) if applicable else None


def _criterion_complete(criterion: TrialCriterionAggregate, variant: TrialVariantAggregate) -> bool:
    return (
        variant.judged_runs == variant.total_runs
        and criterion.unknown == 0
        and criterion.passed + criterion.failed == variant.total_runs
    )


def _overall_comparable(variant: TrialVariantAggregate, baseline: TrialVariantAggregate) -> bool:
    if variant.judged_runs != variant.total_runs or baseline.judged_runs != baseline.total_runs:
        return False
    for criterion, reference in zip(variant.criteria, baseline.criteria, strict=True):
        if criterion.not_applicable == variant.total_runs and reference.not_applicable == baseline.total_runs:
            continue
        if not _criterion_complete(criterion, variant) or not _criterion_complete(reference, baseline):
            return False
    return True


def build_trial_comparison_report(
    snapshot: TrialEvaluationSnapshot, judgments: list[TrialRunJudgment]
) -> TrialComparisonReport:
    expected = {run.launch_id: run for run in snapshot.runs}
    if len(judgments) != len(expected) or {judgment.launch_id for judgment in judgments} != set(expected):
        raise ValueError("The evaluation does not contain exactly one outcome for every requested run.")
    criteria_ids = {criterion.id for criterion in snapshot.criteria}
    scored: list[TrialRunJudgment] = []
    for judgment in judgments:
        if judgment.variant_id != expected[judgment.launch_id].variant_id:
            raise ValueError("A judgment belongs to a different variant.")
        if judgment.status == "judged":
            if (
                len(judgment.criteria) != len(criteria_ids)
                or {verdict.criterion_id for verdict in judgment.criteria} != criteria_ids
            ):
                raise ValueError("A judgment does not cover the saved rubric exactly once.")
            scored.append(
                judgment.model_copy(
                    update={"score": _pass_rate(judgment.criteria), "coverage": _coverage(judgment.criteria)}
                )
            )
        else:
            if judgment.criteria:
                raise ValueError("Excluded runs and judge failures cannot carry quality verdicts.")
            scored.append(judgment.model_copy(update={"score": None, "coverage": None}))

    variants: list[TrialVariantAggregate] = []
    for requested_variant in snapshot.request.variants:
        runs = [run for run in scored if run.variant_id == requested_variant.id]
        verdicts = [verdict for run in runs if run.status == "judged" for verdict in run.criteria]
        aggregates: list[TrialCriterionAggregate] = []
        for criterion in snapshot.criteria:
            matching = [verdict for verdict in verdicts if verdict.criterion_id == criterion.id]
            counts = Counter(verdict.verdict for verdict in matching)
            aggregates.append(
                TrialCriterionAggregate(
                    criterion_id=criterion.id,
                    passed=counts["pass"],
                    failed=counts["fail"],
                    unknown=counts["unknown"],
                    not_applicable=counts["not_applicable"],
                    pass_rate=_pass_rate(matching),
                    coverage=_coverage(matching),
                )
            )
        variants.append(
            TrialVariantAggregate(
                variant_id=requested_variant.id,
                label=requested_variant.label,
                is_baseline=requested_variant.id == snapshot.request.baseline_variant_id,
                total_runs=len(runs),
                judged_runs=sum(run.status == "judged" for run in runs),
                excluded_runs=sum(run.status == "excluded" for run in runs),
                judge_errors=sum(run.status == "judge_error" for run in runs),
                score=mean([run.score for run in runs if run.score is not None])
                if any(run.score is not None for run in runs)
                else None,
                coverage=_coverage(verdicts),
                criteria=aggregates,
            )
        )
    baseline = next(variant for variant in variants if variant.is_baseline)
    compared: list[TrialVariantAggregate] = []
    for variant in variants:
        criteria = [
            criterion.model_copy(
                update={
                    "baseline_delta": criterion.pass_rate - reference.pass_rate
                    if (
                        criterion.pass_rate is not None
                        and reference.pass_rate is not None
                        and _criterion_complete(criterion, variant)
                        and _criterion_complete(reference, baseline)
                    )
                    else None
                }
            )
            for criterion, reference in zip(variant.criteria, baseline.criteria, strict=True)
        ]
        delta = (
            variant.score - baseline.score
            if variant.score is not None and baseline.score is not None and _overall_comparable(variant, baseline)
            else None
        )
        compared.append(variant.model_copy(update={"criteria": criteria, "baseline_delta": delta}))

    summary: list[str] = []
    for variant in compared:
        score = f"{variant.score:.0%} pass rate" if variant.score is not None else "no decisive quality score"
        coverage = (
            f"{variant.coverage:.0%} rubric coverage" if variant.coverage is not None else "no applicable verdicts"
        )
        difference = ""
        if not variant.is_baseline:
            difference = (
                f", {variant.baseline_delta * 100:+.0f} percentage points versus baseline"
                if variant.baseline_delta is not None
                else ", baseline difference unavailable because the judged evidence is not fully comparable"
            )
        summary.append(
            f"{variant.label}: {score}, {coverage}, {variant.judged_runs}/{variant.total_runs} runs judged{difference}."
        )
    revision = snapshot.rubric_document.get("revision")
    return TrialComparisonReport(
        evaluation_id=snapshot.evaluation_id,
        context_id=snapshot.context_id,
        created_at=snapshot.created_at,
        completed_at=datetime.now(UTC),
        summary="\n".join(summary),
        rubric_source=snapshot.request.rubric_source,
        rubric_revision=revision if isinstance(revision, int) and not isinstance(revision, bool) else 0,
        criteria=snapshot.criteria,
        baseline_variant_id=snapshot.request.baseline_variant_id,
        judge_model=snapshot.judge_model,
        judge_prompt_version=snapshot.judge_prompt_version,
        variants=compared,
        runs=scored,
        evidence=snapshot.runs,
        limitations=[
            "These scores use mock default criteria, not a reviewed rubric for this scout.",
            "Each run scores pass verdicts divided by pass and fail verdicts. Variant scores average runs with a decisive score; unknown and not applicable verdicts are excluded.",
            "Rubric coverage is the fraction of applicable verdicts that are pass or fail. Execution failures and judge errors are listed separately.",
            "Differences are descriptive results from these runs, not evidence of statistical significance or a reliable winner.",
            "Project data remains live. Shared starting context does not freeze every source a scout can read.",
            "Evidence quotes are checked against saved text. The judge does not independently verify external sources or measure recall.",
            *sorted({limitation for run in snapshot.runs for limitation in run.limitations}),
        ],
    )
