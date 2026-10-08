import { dayjs } from 'lib/dayjs'

import type {
    TrialComparisonReportApi,
    TrialCriterionAggregateApi,
    TrialCriterionVerdictApi,
    TrialEvaluationCriterionApi,
    TrialRunEvidenceApi,
    TrialRunJudgmentApi,
    TrialVariantAggregateApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { ScoutTrialRow } from './scoutTrialUtils'

export type TrialVerdictCounts = Pick<TrialCriterionAggregateApi, 'passed' | 'failed' | 'unknown' | 'not_applicable'>

export function trialRunVerdictCounts(criteria: TrialCriterionVerdictApi[]): TrialVerdictCounts {
    return {
        passed: criteria.filter((criterion) => criterion.verdict === 'pass').length,
        failed: criteria.filter((criterion) => criterion.verdict === 'fail').length,
        unknown: criteria.filter((criterion) => criterion.verdict === 'unknown').length,
        not_applicable: criteria.filter((criterion) => criterion.verdict === 'not_applicable').length,
    }
}

export function trialVariantVerdictCounts(criteria: TrialCriterionAggregateApi[]): TrialVerdictCounts {
    return criteria.reduce(
        (counts, criterion) => ({
            passed: counts.passed + criterion.passed,
            failed: counts.failed + criterion.failed,
            unknown: counts.unknown + criterion.unknown,
            not_applicable: counts.not_applicable + criterion.not_applicable,
        }),
        { passed: 0, failed: 0, unknown: 0, not_applicable: 0 }
    )
}

export function trialVerdictLabel(verdict: TrialCriterionVerdictApi['verdict']): string {
    return {
        pass: 'Passed',
        fail: 'Failed',
        unknown: 'Unknown',
        not_applicable: 'Not applicable',
    }[verdict]
}

export interface TrialVersionResult {
    variant: TrialVariantAggregateApi
    letter: string
    rank: number
    counts: TrialVerdictCounts
    runs: TrialRunJudgmentApi[]
    settings: string[]
    prompt: string
    costUsd: number | null
    averageDurationSeconds: number | null
}

export function trialVersionResults(report: TrialComparisonReportApi, rows: ScoutTrialRow[]): TrialVersionResult[] {
    const baselineEvidence = report.evidence.filter((run) => run.variant_id === report.baseline_variant_id)
    const versions = report.variants.map((variant, index) => {
        const runs = report.runs.filter((run) => run.variant_id === variant.variant_id)
        const evidence = report.evidence.filter((run) => run.variant_id === variant.variant_id)
        const results = runs.map((run) => rows.find((row) => row.launchId === run.launch_id)?.result)
        const costs = results.map((result) => result?.cost_usd)
        const durations = results.map((result) => {
            if (!result?.started_at || !result.completed_at) {
                return null
            }
            const seconds = dayjs(result.completed_at).diff(dayjs(result.started_at), 'seconds', true)
            return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
        })
        return {
            variant,
            letter: String.fromCharCode(65 + index),
            rank: 0,
            counts: trialVariantVerdictCounts(variant.criteria),
            runs,
            settings: [...new Set(evidence.map((run) => `${run.model} · ${run.reasoning_effort}`))],
            prompt: variant.is_baseline ? 'Baseline prompt' : trialPromptLabel(evidence, baselineEvidence),
            costUsd:
                results.length === variant.total_runs &&
                costs.every((cost): cost is number => cost != null && Number.isFinite(cost))
                    ? costs.reduce((sum, cost) => sum + cost, 0)
                    : null,
            averageDurationSeconds:
                results.length === variant.total_runs &&
                durations.length > 0 &&
                durations.every((duration): duration is number => duration !== null)
                    ? durations.reduce((sum, duration) => sum + duration, 0) / durations.length
                    : null,
        }
    })
    versions.sort((left, right) => right.counts.passed - left.counts.passed)
    for (const [index, version] of versions.entries()) {
        version.rank =
            index > 0 && version.counts.passed === versions[index - 1].counts.passed
                ? versions[index - 1].rank
                : index + 1
    }
    return versions
}

export interface TrialCheckCell {
    label: string
    description: string
    state: 'pass' | 'fail' | 'unknown' | 'not_applicable'
    signature: string
}

export interface TrialCheckRow {
    criterion: TrialEvaluationCriterionApi
    cells: TrialCheckCell[]
    differs: boolean
}

export function trialCheckRows(
    criteria: TrialEvaluationCriterionApi[],
    versions: TrialVersionResult[]
): TrialCheckRow[] {
    return criteria.map((criterion) => {
        const cells = versions.map(({ variant }): TrialCheckCell => {
            const counts = variant.criteria.find((item) => item.criterion_id === criterion.id)
            const passed = counts?.passed ?? 0
            const failed = counts?.failed ?? 0
            const unknown = counts?.unknown ?? 0
            const notApplicable = counts?.not_applicable ?? 0
            const missing = Math.max(0, variant.total_runs - passed - failed - unknown - notApplicable)
            const judged = passed + failed
            const undecided = unknown + missing > 0
            const state = failed > 0 ? 'fail' : undecided ? 'unknown' : judged > 0 ? 'pass' : 'not_applicable'
            return {
                label: judged > 0 ? `${passed}/${judged}${undecided ? ' ?' : ''}` : undecided ? '?' : '–',
                description: `${passed} passed, ${failed} failed, ${unknown} unknown, ${notApplicable} not applicable${missing ? `, ${missing} missing` : ''}`,
                state,
                signature: `${passed}/${failed}/${unknown}/${notApplicable}/${missing}`,
            }
        })
        return { criterion, cells, differs: new Set(cells.map((cell) => cell.signature)).size > 1 }
    })
}

export function trialOrderedVerdicts(
    verdicts: TrialCriterionVerdictApi[],
    criteria: TrialEvaluationCriterionApi[]
): TrialCriterionVerdictApi[] {
    const priority = { fail: 0, unknown: 1, pass: 2, not_applicable: 3 }
    const rubricOrder = new Map(criteria.map((criterion, index) => [criterion.id, index]))
    return [...verdicts].sort(
        (left, right) =>
            priority[left.verdict] - priority[right.verdict] ||
            (rubricOrder.get(left.criterion_id) ?? criteria.length) -
                (rubricOrder.get(right.criterion_id) ?? criteria.length)
    )
}

export function trialPromptLabel(runs: TrialRunEvidenceApi[], baselineRuns: TrialRunEvidenceApi[]): string {
    const hashes = new Set(runs.map((run) => run.skill_body_sha256).filter(Boolean))
    const baselineHashes = new Set(baselineRuns.map((run) => run.skill_body_sha256).filter(Boolean))
    if (!hashes.size || !baselineHashes.size) {
        return 'Prompt unavailable'
    }
    if (hashes.size !== 1 || baselineHashes.size !== 1) {
        return 'Prompts differ between runs'
    }
    return [...hashes][0] === [...baselineHashes][0] ? 'Same prompt as baseline' : 'Different prompt from baseline'
}
