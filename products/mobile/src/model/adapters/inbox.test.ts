import { inboxFromReports, reportsFromPages } from './inbox'
import { reportFixture } from './testFixtures'

describe('inbox adapters', () => {
    test('keeps the first place of a report that a later page ranks again', () => {
        const page = (ids: string[], next: string | null) => ({
            results: ids.map((id) => reportFixture({ id })),
            count: 3,
            next,
        })
        const reports = reportsFromPages([page(['a', 'b'], 'next'), page(['b', 'c'], null)])
        expect(reports.map((report) => report.id)).toEqual(['a', 'b', 'c'])
    })

    test('maps reports: input needed, agent claims, closed reports and model score', () => {
        const items = inboxFromReports([
            reportFixture({
                id: 'a',
                status: 'pending_input',
                source_products: ['signals_scout', 'session_replay'],
                ranking: { scores: { action: 0.9, pr_merged: 0.42 } },
            }),
            reportFixture({
                id: 'b',
                assignee: { kind: 'task', user: null, task_id: 't1', agent: null, claimed_at: null },
            }),
            reportFixture({ id: 'c', status: 'resolved', source_products: ['freshdesk'], ranking: null }),
            reportFixture({ id: 'd', implementation_pr_url: 'https://github.com/example/app/pull/9' }),
            reportFixture({
                id: 'e',
                pull_requests: [
                    {
                        url: 'https://github.com/example/app/pull/10',
                        state: 'closed',
                        merged: true,
                        review_decision: null,
                    },
                ],
            }),
        ])
        expect(items).toMatchObject([
            {
                reportId: 'a',
                needsInput: true,
                sourceProduct: 'session_replay',
                accent: 'alert',
                state: 'open',
                modelScore: 0.42,
            },
            { reportId: 'b', needsInput: false, agent: { name: 'PostHog' }, modelScore: null },
            {
                reportId: 'c',
                state: 'done',
                accent: 'resolved',
                sourceProduct: 'other',
                sourceLabel: 'Report',
                modelScore: null,
            },
            { reportId: 'd', pullRequestUrl: 'https://github.com/example/app/pull/9' },
            { reportId: 'e', pullRequestState: 'merged' },
        ])
        expect(items[0]?.agent).toBeUndefined()
        expect(items[0]?.pullRequestUrl).toBeUndefined()
        expect(items[3]?.pullRequestState).toBeUndefined()
    })
})
