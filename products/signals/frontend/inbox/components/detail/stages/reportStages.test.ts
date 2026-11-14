import { SignalReport, SignalReportStatus } from '../../../types'
import { currentReportStage, reportStageProgress } from './reportStages'

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
    ] as const)('opens a report with %s on its stage', (_name, overrides, expected) => {
        expect(currentReportStage(report(overrides as Partial<SignalReport>))).toBe(expected)
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
