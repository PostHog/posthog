import { myAgentClaim, myClaim, teammateClaim, makeReport } from '../__mocks__/inboxMocks'
import { SignalReportStatus } from '../types'
import {
    claimKeyIntent,
    isForYouReport,
    reportFactStatus,
    reportOwnerKind,
    reportOwnerLabel,
    suggestedOwnerName,
} from './reportFacts'

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

    const key = (
        modifiers: Partial<Record<'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey', boolean>> = {}
    ): {
        metaKey: boolean
        ctrlKey: boolean
        shiftKey: boolean
        altKey: boolean
    } => ({ metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...modifiers })

    test.each([
        ['U claims a report with no owner', key(), true, { canClaim: true, canUnclaim: false }, 'claim'],
        ['U does not release my claim', key(), true, { canClaim: false, canUnclaim: true }, null],
        [
            'Cmd+U releases my claim on a Mac',
            key({ metaKey: true }),
            true,
            { canClaim: false, canUnclaim: true },
            'unclaim',
        ],
        ['Cmd+U does not claim', key({ metaKey: true }), true, { canClaim: true, canUnclaim: false }, null],
        [
            'Ctrl+U releases my claim off a Mac',
            key({ ctrlKey: true }),
            false,
            { canClaim: false, canUnclaim: true },
            'unclaim',
        ],
        ['Ctrl+U does nothing on a Mac', key({ ctrlKey: true }), true, { canClaim: true, canUnclaim: true }, null],
        ['Shift+U does nothing', key({ shiftKey: true }), true, { canClaim: true, canUnclaim: true }, null],
    ])('%s', (_name, event, isMac, state, expected) => {
        expect(claimKeyIntent(event, isMac, state)).toBe(expected)
    })

    test.each([
        ['a report suggested to me', { is_suggested_reviewer: true }, true],
        ['a report I claimed', { assignee: myClaim }, true],
        ['a report my agent claimed', { assignee: myAgentClaim }, true],
        ['a report a teammate claimed', { assignee: teammateClaim }, false],
        ['a report with no relation to me', {}, false],
        [
            'a suggested report still in research',
            { is_suggested_reviewer: true, status: SignalReportStatus.IN_PROGRESS },
            false,
        ],
        [
            'a suggested report that is already addressed',
            { is_suggested_reviewer: true, already_addressed: true },
            false,
        ],
    ])('%s is for me: %s', (_name, overrides, expected) => {
        const report = makeReport({ status: SignalReportStatus.READY, ...overrides } as Parameters<
            typeof makeReport
        >[0])
        expect(isForYouReport(report, myClaim.user?.uuid ?? null)).toBe(expected)
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

    const reviewer = {
        github_login: 'octocat',
        github_name: 'Octo Cat',
        relevant_commits: [],
        user: { id: 1, uuid: 'u-1', email: 'octo@example.com', first_name: 'Octo', last_name: 'Cat' },
    }

    test.each([
        ['no owner and no reviewers', 'none' as const, null, [], 'No owner'],
        ['no owner and a reviewer', 'none' as const, null, [reviewer], 'Suggested for Octo Cat'],
        [
            'no owner and a reviewer with no linked user',
            'none' as const,
            null,
            [{ ...reviewer, user: null, github_name: null }],
            'Suggested for octocat',
        ],
        ['a teammate claim and a reviewer', 'teammate' as const, 'Ada Byron', [reviewer], 'Claimed by Ada Byron'],
    ])('%s gives the owner label', (_name, kind, holderName, reviewers, expected) => {
        expect(reportOwnerLabel(kind, holderName, suggestedOwnerName(reviewers))).toBe(expected)
    })
})
