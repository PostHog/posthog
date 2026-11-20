import { myAgentClaim, myClaim, teammateClaim, makeReport } from '../__mocks__/inboxMocks'
import { SignalReportStatus } from '../types'
import { reportFactStatus, reportOwnerKind } from './reportFacts'

describe('reportFacts', () => {
    const openPullRequest = { url: 'https://github.com/example/repo/pull/7', state: 'open' as const, merged: false }

    test.each([
        ['a ready report with no work', {}, 'Open'],
        ['a ready report with an open pull request', { pull_requests: [openPullRequest] }, 'Pull request ready'],
        ['a ready report with a run in flight', { implementation_in_flight: true }, 'Run in progress'],
        [
            'a resolved report that still lists a pull request',
            { status: SignalReportStatus.RESOLVED, pull_requests: [openPullRequest] },
            'Resolved',
        ],
        ['a report in research', { status: SignalReportStatus.IN_PROGRESS }, 'Research in progress'],
    ])('%s reads as its current step', (_name, overrides, expected) => {
        const report = makeReport({ status: SignalReportStatus.READY, ...overrides } as Parameters<
            typeof makeReport
        >[0])
        expect(reportFactStatus(report)).toBe(expected)
    })

    test.each([
        ['no claim', null, 'none'],
        ['my claim', myClaim, 'me'],
        ['my agent', myAgentClaim, 'my-agent'],
        ['a teammate', teammateClaim, 'teammate'],
    ])('%s gives the owner kind', (_name, assignee, expected) => {
        const me = myClaim.user?.uuid ?? null
        expect(reportOwnerKind({ assignee }, me)).toBe(expected)
    })
})
