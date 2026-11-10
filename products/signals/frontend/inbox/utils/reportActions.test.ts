import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { canResolveReport } from '@posthog/agent-contracts/signal-report-state'

import { myAgentClaim, myClaim, teammateClaim } from '../__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from '../types'
import { canCreateImplementationPr, canMonitorReport, implementationClaimStep } from './reportActions'

describe('reportActions', () => {
    it.each([
        [SignalReportStatus.READY, true],
        [SignalReportStatus.PENDING_INPUT, true],
        [SignalReportStatus.FAILED, true],
        [SignalReportStatus.MONITORING, true],
        [SignalReportStatus.CLOSED, true],
        [SignalReportStatus.POTENTIAL, false],
        [SignalReportStatus.CANDIDATE, false],
        [SignalReportStatus.IN_PROGRESS, false],
        [SignalReportStatus.RESOLVED, false],
        [SignalReportStatus.SUPPRESSED, false],
        [SignalReportStatus.DELETED, false],
    ] as const)('allows resolution for %s: %s', (status, expected) => {
        expect(canResolveReport({ status } as SignalReport)).toBe(expected)
    })

    it.each([
        [SignalReportStatus.READY, true, true],
        [SignalReportStatus.READY, false, false],
        [SignalReportStatus.PENDING_INPUT, true, true],
        [SignalReportStatus.FAILED, true, true],
        [SignalReportStatus.MONITORING, true, false],
        [SignalReportStatus.CLOSED, true, false],
        [SignalReportStatus.RESOLVED, true, false],
        [SignalReportStatus.SUPPRESSED, true, false],
    ] as const)('gates manual Monitoring for %s with server capability %s: %s', (status, enabled, expected) => {
        expect(
            canMonitorReport({ status, ...(enabled ? { monitoring_started_at: null } : {}) } as SignalReport, true)
        ).toBe(expected)
    })

    it.each([false, true])('offers Monitoring only with follow-up checks: %s', (hasFollowUpChecks) => {
        expect(
            canMonitorReport(
                { status: SignalReportStatus.READY, monitoring_started_at: null } as SignalReport,
                hasFollowUpChecks
            )
        ).toBe(hasFollowUpChecks)
    })

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

    it.each([
        ['without a repository', null, false],
        ['with a repository', 'posthog/posthog', true],
    ] as const)('offers implementation on a scout self-improvement report %s: %s', (_, repoSlug, expected) => {
        expect(
            canCreateImplementationPr({
                id: 'report',
                status: SignalReportStatus.PENDING_INPUT,
                is_self_improvement_report: true,
                repo_slug: repoSlug,
            } as SignalReport)
        ).toBe(expected)
    })

    // Each step has to match what the server does with the claim. A block it would not apply strands the user,
    // and a start it would refuse fails the run.
    it.each([
        { name: 'no claim', report: { assignee: null }, expected: { kind: 'start' } },
        { name: 'my claim', report: { assignee: myClaim }, expected: { kind: 'start' } },
        {
            name: "a task's claim",
            report: { assignee: { ...myClaim, kind: 'task', user: null, task_id: 'task-1' } },
            expected: { kind: 'start' },
        },
        { name: "my agent's claim", report: { assignee: myAgentClaim }, expected: { kind: 'confirm_own_agent' } },
        {
            name: "a teammate's claim",
            report: { assignee: teammateClaim },
            expected: { kind: 'take_over', holder: teammateClaim.user },
        },
        {
            name: 'a run in flight',
            report: { assignee: myClaim, implementation_in_flight: true },
            expected: { kind: 'blocked', reason: 'A pull request run is already in progress for this report.' },
        },
    ] as const)('decides the claim step for $name', ({ report, expected }) => {
        expect(implementationClaimStep(report as unknown as SignalReport, MOCK_DEFAULT_USER.uuid)).toEqual(expected)
    })
})
