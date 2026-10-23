import { SignalReport, SignalReportStatus } from '../types'
import { canCreateImplementationPr, canResolveReport } from './reportActions'

describe('reportActions', () => {
    describe('canResolveReport', () => {
        it.each([
            [SignalReportStatus.READY, true],
            [SignalReportStatus.PENDING_INPUT, true],
            [SignalReportStatus.FAILED, true],
            [SignalReportStatus.POTENTIAL, false],
            [SignalReportStatus.CANDIDATE, false],
            [SignalReportStatus.IN_PROGRESS, false],
            [SignalReportStatus.RESOLVED, false],
            [SignalReportStatus.SUPPRESSED, false],
        ] as const)('allows resolution for %s: %s', (status, expected) => {
            expect(canResolveReport({ status } as SignalReport)).toBe(expected)
        })
    })

    describe('canCreateImplementationPr', () => {
        it.each([
            ['the plan itself', false, 'report'],
            ['a step of a plan', true, 'plan'],
        ] as const)('offers implementation on %s: %s', (_, expected, planId) => {
            const report = {
                id: 'report',
                status: SignalReportStatus.READY,
                actionability: 'immediately_actionable',
                plan: { id: planId, title: 'Plan', status: 'ready', steps: [] },
            } as unknown as SignalReport

            expect(canCreateImplementationPr(report)).toBe(expected)
        })
    })
})
