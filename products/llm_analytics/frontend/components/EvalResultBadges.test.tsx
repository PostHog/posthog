import { EvaluationRun } from '../evaluations/types'
import { getEvalBadgeProps, getEvalSummaries } from './EvalResultBadges'

function makeRun(overrides: Partial<EvaluationRun> = {}): EvaluationRun {
    return {
        id: 'run-1',
        evaluation_id: 'eval-1',
        evaluation_name: 'Test Eval',
        generation_id: 'gen-1',
        trace_id: 'trace-1',
        timestamp: '2026-04-10T12:00:00Z',
        result: true,
        reasoning: '',
        status: 'completed',
        ...overrides,
    }
}

describe('getEvalSummaries', () => {
    it('returns empty array for empty input', () => {
        expect(getEvalSummaries([])).toEqual([])
    })

    it('groups runs by evaluation_id and counts them', () => {
        const runs = [
            makeRun({ id: 'r1', evaluation_id: 'eval-a', timestamp: '2026-04-10T12:00:00Z' }),
            makeRun({ id: 'r2', evaluation_id: 'eval-a', timestamp: '2026-04-09T12:00:00Z' }),
            makeRun({ id: 'r3', evaluation_id: 'eval-b', timestamp: '2026-04-10T12:00:00Z' }),
        ]
        const summaries = getEvalSummaries(runs)
        expect(summaries).toHaveLength(2)

        const evalA = summaries.find((s) => s.latestRun.evaluation_id === 'eval-a')!
        expect(evalA.runCount).toBe(2)
        expect(evalA.latestRun.id).toBe('r1')

        const evalB = summaries.find((s) => s.latestRun.evaluation_id === 'eval-b')!
        expect(evalB.runCount).toBe(1)
    })

    it('picks the latest run regardless of input order', () => {
        const older = makeRun({ id: 'old', evaluation_id: 'eval-a', timestamp: '2026-04-01T00:00:00Z' })
        const newer = makeRun({ id: 'new', evaluation_id: 'eval-a', timestamp: '2026-04-10T00:00:00Z' })

        const ascResult = getEvalSummaries([older, newer])
        expect(ascResult[0].latestRun.id).toBe('new')

        const descResult = getEvalSummaries([newer, older])
        expect(descResult[0].latestRun.id).toBe('new')
    })

    it('handles a single run', () => {
        const summaries = getEvalSummaries([makeRun()])
        expect(summaries).toHaveLength(1)
        expect(summaries[0].runCount).toBe(1)
    })
})

describe('getEvalBadgeProps', () => {
    it.each([
        ['failed status', makeRun({ status: 'failed' }), { type: 'danger', label: 'Error' }],
        ['running status', makeRun({ status: 'running' }), { type: 'primary', label: 'Running' }],
        ['null result', makeRun({ result: null }), { type: 'muted', label: 'N/A' }],
        ['true result', makeRun({ result: true }), { type: 'success', label: 'True' }],
        ['false result', makeRun({ result: false }), { type: 'danger', label: 'False' }],
    ])('%s', (_name, run, expected) => {
        const props = getEvalBadgeProps(run)
        expect(props.type).toBe(expected.type)
        expect(props.label).toBe(expected.label)
        expect(props.icon).toBeTruthy()
    })

    it('prioritizes failed status over result value', () => {
        const props = getEvalBadgeProps(makeRun({ status: 'failed', result: true }))
        expect(props.label).toBe('Error')
    })

    it('prioritizes running status over result value', () => {
        const props = getEvalBadgeProps(makeRun({ status: 'running', result: true }))
        expect(props.label).toBe('Running')
    })
})
