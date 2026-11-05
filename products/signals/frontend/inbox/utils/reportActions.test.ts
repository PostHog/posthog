import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { myAgentClaim, myClaim, teammateClaim } from '../__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from '../types'
import {
    canCreateImplementationPr,
    canMonitorReport,
    canResolveReport,
    implementationClaimDisabledReason,
} from './reportActions'

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

    // The server refuses a new implementation task under any claim but the starter's own user claim, so a
    // missed case here offers a Create PR that always fails.
    it.each([
        { name: 'no claim', assignee: null, expected: null },
        { name: 'my claim', assignee: myClaim, expected: null },
        { name: "a teammate's claim", assignee: teammateClaim, expected: 'Robin is working on this report.' },
        { name: "my agent's claim", assignee: myAgentClaim, expected: 'Your agent is working on this report.' },
        {
            name: "a task's claim",
            assignee: { ...myClaim, kind: 'task', user: null, task_id: 'task-1' },
            expected: 'A task is already working on this report.',
        },
    ] as const)('gates implementation on $name', ({ assignee, expected }) => {
        expect(implementationClaimDisabledReason({ assignee } as unknown as SignalReport, MOCK_DEFAULT_USER.uuid)).toBe(
            expected
        )
    })
})
