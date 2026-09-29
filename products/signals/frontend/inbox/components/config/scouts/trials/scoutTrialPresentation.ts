import type {
    TrialCriterionAggregateApi,
    TrialCriterionVerdictApi,
    TrialRunEvidenceApi,
} from 'products/signals/frontend/generated/api.schemas'

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
        unknown: 'Not enough evidence',
        not_applicable: 'Not applicable',
    }[verdict]
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
