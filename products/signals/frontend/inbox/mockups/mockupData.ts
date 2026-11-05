// Invented content for the Today-style inbox mockups. Nothing here comes from a real project.

export type MockStage = 'review' | 'decide' | 'watching' | 'done'

export interface MockEvidence {
    id: string
    headline: string
    source: string
    meta: string
    date: string
}

export interface MockPullRequest {
    number: number
    state: 'open' | 'draft' | 'merged'
    branch: string
    files: { path: string; additions: number; deletions: number }[]
    checks: { passed: number; failed: number; running: number; failedName?: string }
}

export interface MockRun {
    label: string
    when: string
    cost: string
}

export interface MockActivity {
    when: string
    text: string
}

export interface MockTrend {
    label: string
    value: string
    values: number[]
    labels: string[]
}

export interface MockReport {
    id: string
    title: string
    priority: 'P1' | 'P2' | 'P3'
    source: string
    sources: string
    updated: string
    stage: MockStage
    stateLabel?: string
    abstract: string
    whatHappened: string
    whyItMatters: string
    proposal: string
    nextStep: string
    nextStepNote?: string
    owner: string
    reviewers: string[]
    pullRequest?: MockPullRequest
    runs: MockRun[]
    activity: MockActivity[]
    spend: string
    evidence: MockEvidence[]
    evidenceCount: number
    trend?: MockTrend
    impact?: string
}

const DAYS = ['Oct 24', 'Oct 25', 'Oct 26', 'Oct 27', 'Oct 28', 'Oct 29', 'Oct 30', 'Oct 31', 'Nov 1', 'Nov 2', 'Nov 3']

export const MOCK_REPORTS: MockReport[] = [
    {
        id: 'checkout-verification',
        title: 'Checkout fails for cards that ask for a second verification step',
        priority: 'P1',
        source: 'error_tracking',
        sources: 'Error tracking, Session replay, Support',
        updated: '2 hours ago',
        stage: 'review',
        stateLabel: 'Fix ready for review',
        abstract:
            'Since Monday, about 1 in 40 card payments ends on a blank page when the bank asks for a verification code. The payment goes through, but the order is not saved, so people pay twice or contact support.',
        whatHappened:
            'The verification popup returns to the checkout page without the session cookie. The order handler reads the cart from the session, finds nothing, and throws.',
        whyItMatters:
            'Each failure is a paid order that is not recorded. Tickets about double charges went up in the same week.',
        proposal:
            'Keep the cart id in the return URL of the verification step, and read the cart from it when the session is empty. Add a test for the return path.',
        nextStep: 'Review PR #4821',
        nextStepNote: '1 check failed: e2e / checkout-mobile',
        owner: 'You',
        reviewers: ['Ada Lovelace', 'Grace Hopper'],
        pullRequest: {
            number: 4821,
            state: 'open',
            branch: 'fix/checkout-verification-return',
            files: [
                { path: 'checkout/complete.ts', additions: 38, deletions: 9 },
                { path: 'checkout/verification.ts', additions: 12, deletions: 3 },
                { path: 'checkout/complete.test.ts', additions: 14, deletions: 0 },
            ],
            checks: { passed: 12, failed: 1, running: 0, failedName: 'e2e / checkout-mobile' },
        },
        runs: [
            { label: 'Read 412 error events and 18 recordings', when: 'Mon 09:12', cost: '$0.42' },
            { label: 'Wrote the fix and opened the pull request', when: 'Mon 10:40', cost: '$0.61' },
            { label: 'Fixed a failing unit test', when: 'Tue 08:05', cost: '$0.17' },
        ],
        activity: [
            { when: 'Mon 09:02', text: 'Error tracking found a new error in completeOrder' },
            { when: 'Mon 09:12', text: 'An agent started to investigate' },
            { when: 'Mon 10:40', text: 'Pull request #4821 opened' },
            { when: 'Tue 08:05', text: 'Unit tests pass' },
            { when: 'Tue 08:30', text: 'Ada Lovelace was asked to review' },
        ],
        spend: '$1.20',
        evidence: [
            {
                id: 'e1',
                headline: 'TypeError: cannot read "items" of undefined in completeOrder',
                source: 'error_tracking',
                meta: '412 events, 96 people',
                date: 'Nov 2',
            },
            {
                id: 'e2',
                headline: 'Recording: payment approved, then a blank page for 40 seconds',
                source: 'session_replay',
                meta: '18 similar recordings',
                date: 'Nov 2',
            },
            {
                id: 'e3',
                headline: 'Support ticket: charged twice for one order',
                source: 'conversations',
                meta: '7 tickets',
                date: 'Nov 3',
            },
        ],
        evidenceCount: 11,
        trend: {
            label: 'Checkout errors per day',
            value: '33 yesterday',
            values: [2, 1, 3, 2, 2, 1, 2, 24, 31, 29, 33],
            labels: DAYS,
        },
        impact: 'After the merge, a check watches checkout errors. The goal is fewer than 3 a day for 7 days.',
    },
    {
        id: 'reset-email-spam',
        title: 'Password reset emails go to spam for new accounts',
        priority: 'P2',
        source: 'conversations',
        sources: 'Support, Logs',
        updated: '5 hours ago',
        stage: 'decide',
        abstract:
            'People who sign up with a company email do not get the password reset email. 14 support tickets in 7 days say the same thing.',
        whatHappened:
            'Reset emails are sent from the app domain, which has no DKIM record. Mail servers with strict rules move them to spam.',
        whyItMatters: 'People who cannot reset their password stop at the login page. Most of them are new accounts.',
        proposal:
            'Send reset emails from the verified mail domain, and add the missing DKIM record to the setup checklist.',
        nextStep: 'Implement',
        owner: 'Nobody yet',
        reviewers: ['Grace Hopper'],
        runs: [{ label: 'Read 14 tickets and the mail logs', when: 'Today 07:40', cost: '$0.21' }],
        activity: [
            { when: 'Today 07:31', text: 'Support grouped 14 tickets' },
            { when: 'Today 07:40', text: 'An agent started to investigate' },
        ],
        spend: '$0.21',
        evidence: [
            {
                id: 'e1',
                headline: 'Support ticket: reset link never arrives',
                source: 'conversations',
                meta: '14 tickets',
                date: 'Nov 4',
            },
            {
                id: 'e2',
                headline: 'Mail log: message marked as spam by the receiving server',
                source: 'logs',
                meta: '230 lines',
                date: 'Nov 4',
            },
        ],
        evidenceCount: 4,
    },
    {
        id: 'search-double-load',
        title: 'Search results load twice on phones',
        priority: 'P2',
        source: 'session_replay',
        sources: 'Session replay, Product analytics',
        updated: 'yesterday',
        stage: 'review',
        stateLabel: 'Fix ready for review',
        abstract:
            'On phones, the search page sends each query two times and shows empty results for a moment. People tap a result in the first list and open the wrong item.',
        whatHappened:
            'The search box sends the query on input and again on blur, and the two answers arrive out of order.',
        whyItMatters: 'Search is the first step for most visits on phones.',
        proposal: 'Cancel the older request when a new one starts, and stop sending on blur.',
        nextStep: 'Review PR #4815',
        owner: 'You',
        reviewers: ['Ada Lovelace'],
        pullRequest: {
            number: 4815,
            state: 'open',
            branch: 'fix/search-single-request',
            files: [{ path: 'search/SearchBox.tsx', additions: 21, deletions: 14 }],
            checks: { passed: 13, failed: 0, running: 0 },
        },
        runs: [{ label: 'Watched 25 recordings and wrote the fix', when: 'Mon 16:20', cost: '$0.58' }],
        activity: [{ when: 'Mon 16:20', text: 'Pull request #4815 opened' }],
        spend: '$0.58',
        evidence: [
            {
                id: 'e1',
                headline: 'Recording: results flash, then the list changes under the tap',
                source: 'session_replay',
                meta: '25 recordings',
                date: 'Nov 3',
            },
        ],
        evidenceCount: 3,
    },
    {
        id: 'trial-import-skip',
        title: 'Trial teams that skip the import step rarely come back after week one',
        priority: 'P2',
        source: 'analytics',
        sources: 'Product analytics',
        updated: '2 days ago',
        stage: 'decide',
        abstract:
            'Teams that skip "Import your data" during setup use the product half as often in week two. 6 in 10 trial teams skip it.',
        whatHappened: 'The import step comes after the invite step, and most teams stop at the invite step.',
        whyItMatters: 'Week two use is the best early sign of a paid plan.',
        proposal: 'Move the import step before the invite step, and add an option to start with sample data.',
        nextStep: 'Implement',
        owner: 'Nobody yet',
        reviewers: [],
        runs: [{ label: 'Compared 2 funnels and 1 retention chart', when: 'Mon 11:00', cost: '$0.33' }],
        activity: [{ when: 'Mon 11:00', text: 'Scout found a drop in week two retention' }],
        spend: '$0.33',
        evidence: [
            {
                id: 'e1',
                headline: 'Funnel: setup steps for trial teams, last 30 days',
                source: 'analytics',
                meta: '1,204 teams',
                date: 'Nov 2',
            },
        ],
        evidenceCount: 2,
    },
    {
        id: 'export-button',
        title: 'Export button stays off after you change a filter',
        priority: 'P3',
        source: 'github',
        sources: 'GitHub',
        updated: '3 days ago',
        stage: 'review',
        stateLabel: 'Fix ready for review',
        abstract: 'The export button does not turn on again after a filter change, until you reload the page.',
        whatHappened: 'The button reads a loading flag that is not reset when the filter request is canceled.',
        whyItMatters: 'Two issues on GitHub ask about it.',
        proposal: 'Reset the loading flag when the request is canceled.',
        nextStep: 'Review PR #4790',
        owner: 'You',
        reviewers: ['Grace Hopper'],
        pullRequest: {
            number: 4790,
            state: 'open',
            branch: 'fix/export-button-state',
            files: [{ path: 'export/exportLogic.ts', additions: 6, deletions: 2 }],
            checks: { passed: 13, failed: 0, running: 0 },
        },
        runs: [{ label: 'Read 2 issues and wrote the fix', when: 'Sat 14:10', cost: '$0.12' }],
        activity: [{ when: 'Sat 14:10', text: 'Pull request #4790 opened' }],
        spend: '$0.12',
        evidence: [
            {
                id: 'e1',
                headline: 'Issue: export is grey after filtering',
                source: 'github',
                meta: '2 issues',
                date: 'Nov 1',
            },
        ],
        evidenceCount: 2,
    },
    {
        id: 'summary-cost',
        title: 'Summaries cost more since the model change',
        priority: 'P3',
        source: 'llm_analytics',
        sources: 'LLM analytics',
        updated: '4 hours ago',
        stage: 'watching',
        stateLabel: 'Check runs until Friday',
        abstract:
            'The summarize tool uses 2.1 times more tokens for each call since Thursday. A check runs until Friday to see if the new prompt limit brings the cost back.',
        whatHappened: 'The new model writes longer answers, and the prompt had no length limit.',
        whyItMatters: 'Summaries are the largest part of the AI spend.',
        proposal: 'The length limit is merged. If the cost is not back by Friday, try the smaller model.',
        nextStep: 'Check runs until Friday',
        owner: 'You',
        reviewers: [],
        runs: [{ label: 'Compared token use before and after the change', when: 'Thu 10:00', cost: '$0.09' }],
        activity: [{ when: 'Fri 09:00', text: 'Pull request #4760 merged' }],
        spend: '$0.09',
        evidence: [
            {
                id: 'e1',
                headline: 'Trace: 3,900 output tokens for one summary',
                source: 'llm_analytics',
                meta: '640 traces',
                date: 'Oct 31',
            },
        ],
        evidenceCount: 3,
    },
    {
        id: 'plan-picker-rage',
        title: 'Rage clicks on the plan picker after the pricing page update',
        priority: 'P3',
        source: 'session_replay',
        sources: 'Session replay',
        updated: '6 hours ago',
        stage: 'watching',
        stateLabel: 'Check runs until Monday',
        abstract: 'People click the plan names many times, because they look like buttons but do nothing.',
        whatHappened: 'The pricing page update made plan names bold and blue.',
        whyItMatters: 'The pricing page is the last step before checkout.',
        proposal: 'The plan names now open the plan details. A check counts rage clicks until Monday.',
        nextStep: 'Check runs until Monday',
        owner: 'Grace Hopper',
        reviewers: [],
        runs: [{ label: 'Watched 12 recordings', when: 'Today 06:00', cost: '$0.14' }],
        activity: [{ when: 'Today 06:00', text: 'Pull request #4801 merged' }],
        spend: '$0.14',
        evidence: [
            {
                id: 'e1',
                headline: 'Recording: 9 clicks on "Teams" in 3 seconds',
                source: 'session_replay',
                meta: '12 recordings',
                date: 'Nov 4',
            },
        ],
        evidenceCount: 2,
    },
    {
        id: 'webhook-retries',
        title: 'Webhook retries no longer pile up for one destination',
        priority: 'P3',
        source: 'logs',
        sources: 'Logs',
        updated: '2 days ago',
        stage: 'done',
        stateLabel: 'Merged',
        abstract: 'Retries for a slow destination now back off, so other destinations do not wait.',
        whatHappened: 'One slow destination took every retry slot.',
        whyItMatters: 'Other webhooks were late by up to 20 minutes.',
        proposal: 'Done.',
        nextStep: 'Resolve',
        owner: 'You',
        reviewers: [],
        runs: [],
        activity: [],
        spend: '$0.40',
        evidence: [],
        evidenceCount: 0,
    },
]

export const LEAD_REPORT = MOCK_REPORTS[0]
export const OPEN_REPORTS = MOCK_REPORTS.filter((report) => report.stage !== 'done')
export const DONE_REPORTS = MOCK_REPORTS.filter((report) => report.stage === 'done')

export function reportsInStage(stage: MockStage): MockReport[] {
    return MOCK_REPORTS.filter((report) => report.stage === stage)
}
