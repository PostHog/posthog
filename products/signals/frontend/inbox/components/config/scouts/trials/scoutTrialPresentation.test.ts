import { trialCheckRows, trialOrderedVerdicts, trialVersionResults } from './scoutTrialPresentation'
import { trialFixtureReport, trialFixtureResult } from './scoutTrialsFixtures'
import type { ScoutTrialRow } from './scoutTrialUtils'

describe('scout trial result presentation', () => {
    const rows: ScoutTrialRow[] = trialFixtureReport.runs.map((run) => ({
        launchId: run.launch_id,
        variant: run.variant_id,
        model: trialFixtureResult.model,
        effort: trialFixtureResult.reasoning_effort,
        status: 'completed',
        startedAt: trialFixtureResult.started_at,
        error: null,
        result: { ...trialFixtureResult, launch_id: run.launch_id, cost_usd: 0.5 },
    }))

    it('ranks by passed checks instead of pass rate and keeps equal totals tied', () => {
        const report = {
            ...trialFixtureReport,
            variants: trialFixtureReport.variants.map((variant) => ({
                ...variant,
                score: variant.is_baseline ? 1 : 0.25,
            })),
        }
        expect(trialVersionResults(report, rows).map(({ variant }) => variant.label)).toEqual([
            'Candidate prompt',
            'Baseline',
        ])
        const tied = {
            ...report,
            variants: report.variants.map((variant) => ({ ...variant, criteria: report.variants[1].criteria })),
        }
        expect(trialVersionResults(tied, rows).map(({ rank }) => rank)).toEqual([1, 1])
        expect(report.variants[0].is_baseline).toBe(true)
    })

    test.each(['missing', 'unknown', 'known', 'zero'] as const)('keeps %s cost distinct from free runs', (state) => {
        const inputs =
            state === 'missing'
                ? rows.slice(1)
                : rows.map((row, index) => ({
                      ...row,
                      result: {
                          ...row.result!,
                          cost_usd: state === 'unknown' && index === 0 ? null : state === 'zero' ? 0 : 0.5,
                      },
                  }))
        const version = trialVersionResults(trialFixtureReport, inputs).find(({ variant }) => variant.is_baseline)!
        expect(version.costUsd).toBe(state === 'known' ? 1 : state === 'zero' ? 0 : null)
        expect(version.averageDurationSeconds).toBe(state === 'missing' ? null : 240)
    })

    test.each([
        [{ passed: 0, failed: 0, unknown: 0, not_applicable: 0 }, '?', 'unknown'],
        [{ passed: 0, failed: 0, unknown: 0, not_applicable: 2 }, '–', 'not_applicable'],
        [{ passed: 1, failed: 0, unknown: 1, not_applicable: 0 }, '1/1 ?', 'unknown'],
        [{ passed: 1, failed: 1, unknown: 0, not_applicable: 0 }, '1/2', 'fail'],
    ] as const)('distinguishes missing and undecided checks from not applicable: %s', (counts, label, state) => {
        const report = {
            ...trialFixtureReport,
            variants: trialFixtureReport.variants.map((variant) => ({
                ...variant,
                criteria: variant.criteria.map((criterion) => ({ ...criterion, ...counts })),
            })),
        }
        const [row] = trialCheckRows(report.criteria, trialVersionResults(report, []))
        expect(row.cells[0]).toMatchObject({ label, state })
        expect(row.differs).toBe(false)
    })

    it('places failed and unknown checks first without changing rubric order within a group', () => {
        const verdicts = trialFixtureReport.runs[0].criteria!
        const criteria = [...trialFixtureReport.criteria].reverse()
        expect(trialOrderedVerdicts([...verdicts].reverse(), criteria).map((verdict) => verdict.criterion_id)).toEqual([
            'evidence',
            'action',
        ])
        expect(
            trialOrderedVerdicts(
                verdicts.map((verdict) => ({ ...verdict, verdict: 'unknown' as const })),
                criteria
            ).map((verdict) => verdict.criterion_id)
        ).toEqual(['action', 'evidence'])
    })
})
