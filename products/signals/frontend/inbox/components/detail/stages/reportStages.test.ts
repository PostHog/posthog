import { SignalReport, SignalReportStatus } from '../../../types'
import { availableReportStages, currentReportStage, reportStageProgress } from './reportStages'

describe('reportStages', () => {
    const report = (overrides: Partial<SignalReport>): SignalReport =>
        ({ status: SignalReportStatus.READY, assignee: null, pull_requests: [], ...overrides }) as SignalReport

    test.each([
        ['no work yet', {}, 'spec'],
        ['claimed', { assignee: { kind: 'user' } }, 'execute'],
        ['a run in flight', { implementation_in_flight: true }, 'execute'],
        [
            'a pull request',
            { implementation_pr_url: 'https://github.com/a/b/pull/1', pull_requests: undefined },
            'execute',
        ],
        ['monitoring', { status: SignalReportStatus.MONITORING, assignee: { kind: 'user' } }, 'measure'],
        ['resolved', { status: SignalReportStatus.RESOLVED }, 'measure'],
        [
            'no change needed, resolved',
            { status: SignalReportStatus.RESOLVED, actionability: 'not_actionable' },
            'spec',
        ],
    ] as const)('opens a report with %s on its stage', (_name, overrides, expected) => {
        expect(currentReportStage(report(overrides as Partial<SignalReport>))).toBe(expected)
    })

    test.each([
        ['not judged yet', { actionability: null }, ['spec', 'execute', 'measure']],
        ['no change needed', { actionability: 'not_actionable' }, ['spec']],
        ['already addressed', { actionability: 'immediately_actionable', already_addressed: true }, ['spec']],
        [
            'no change needed, but claimed',
            { actionability: 'not_actionable', assignee: { kind: 'user' } },
            ['spec', 'execute', 'measure'],
        ],
        [
            'already addressed and monitored',
            { already_addressed: true, monitoring_started_at: '2026-11-01T00:00:00Z' },
            ['spec', 'measure'],
        ],
    ] as const)('shows the stages that apply to a report with %s', (_name, overrides, expected) => {
        expect(availableReportStages(report(overrides as Partial<SignalReport>))).toEqual(expected)
    })

    it('marks the stages before the current one as done', () => {
        const monitoring = report({ status: SignalReportStatus.MONITORING })
        expect(['spec', 'execute', 'measure'].map((stage) => reportStageProgress(stage as 'spec', monitoring))).toEqual(
            ['done', 'done', 'current']
        )
    })

    it('marks every stage of a resolved report as done', () => {
        expect(reportStageProgress('measure', report({ status: SignalReportStatus.RESOLVED }))).toBe('done')
    })
})
