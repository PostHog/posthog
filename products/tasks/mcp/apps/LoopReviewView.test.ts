jest.mock('@posthog/mcp-ui', () => ({ DescriptionList: () => null }), {
    virtual: true,
})
jest.mock('@posthog/quill', () => ({ Button: () => null, Card: () => null, CardContent: () => null }), {
    virtual: true,
})
jest.mock('lucide-react', () => ({ Check: () => null }), { virtual: true })

import {
    describeFixReviewComments,
    describePosthogAccess,
    describeRunBehavior,
    type LoopReviewBehaviors,
    type LoopReviewConnectors,
    type LoopReviewData,
} from './LoopReviewView'

describe('LoopReviewView', () => {
    describe('describeFixReviewComments', () => {
        it.each<[string, LoopReviewBehaviors | undefined, string]>([
            ['fix_review_comments without watch_ci', { fix_review_comments: true, watch_ci: false }, 'Yes'],
            ['fix_review_comments with watch_ci', { fix_review_comments: true, watch_ci: true }, 'Yes'],
            ['watch_ci only', { fix_review_comments: false, watch_ci: true }, 'No'],
            ['neither flag', { fix_review_comments: false, watch_ci: false }, 'No'],
            ['missing behaviors', undefined, 'No'],
            ['iteration cap', { fix_review_comments: true, max_fix_iterations: 5 }, 'Yes (up to 5 iterations)'],
            ['zero iteration cap', { fix_review_comments: true, max_fix_iterations: 0 }, 'Yes (up to 0 iterations)'],
        ])('%s', (_label, behaviors, expected) => {
            expect(describeFixReviewComments(behaviors)).toBe(expected)
        })
    })

    describe('describeRunBehavior', () => {
        it.each<[string, Pick<LoopReviewData, 'triggers' | 'enabled' | 'overlap_policy'>, string]>([
            ['no triggers shows the default overlap policy', {}, 'Manual only · skips overlapping runs'],
            [
                'cron schedule trigger',
                {
                    triggers: [
                        {
                            type: 'schedule',
                            config: { cron_expression: '0 9 * * 1' },
                        },
                    ],
                },
                'Schedule (0 9 * * 1) · skips overlapping runs',
            ],
            [
                'github trigger without events',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: { repository: 'posthog/code' },
                        },
                    ],
                },
                'GitHub (posthog/code) · skips overlapping runs',
            ],
            [
                'github trigger lists its events',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['issues', 'pull_request'],
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: issues, pull_request) · skips overlapping runs',
            ],
            [
                'github trigger with an actions filter',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['issues'],
                                filters: { actions: ['opened'] },
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: issues opened) · skips overlapping runs',
            ],
            [
                'github trigger with singular action alias',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['issues'],
                                filters: { action: 'opened' },
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: issues opened) · skips overlapping runs',
            ],
            [
                'github trigger with dotted event shorthand',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['issues.opened'],
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: issues opened) · skips overlapping runs',
            ],
            [
                'github push trigger with a branch filter',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['push'],
                                filters: { branches: ['main'] },
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: push on main) · skips overlapping runs',
            ],
            [
                'github trigger with a label filter',
                {
                    triggers: [
                        {
                            type: 'github',
                            config: {
                                repository: 'posthog/code',
                                events: ['issues'],
                                filters: { labels: ['bug'] },
                            },
                        },
                    ],
                },
                'GitHub (posthog/code: issues labeled bug) · skips overlapping runs',
            ],
            ['paused loop', { enabled: false }, 'Manual only · paused · skips overlapping runs'],
            ['allow policy', { overlap_policy: 'allow' }, 'Manual only · allows overlapping runs'],
            ['cancel_previous policy', { overlap_policy: 'cancel_previous' }, 'Manual only · cancels the previous run'],
            [
                'unknown policy falls back to the raw value',
                {
                    overlap_policy: 'defer' as unknown as LoopReviewData['overlap_policy'],
                },
                'Manual only · defer',
            ],
        ])('%s', (_label, data, expected) => {
            expect(describeRunBehavior(data)).toBe(expected)
        })
    })

    describe('describePosthogAccess', () => {
        it.each<[string, LoopReviewConnectors | undefined, string]>([
            ['missing connectors', undefined, 'Read-only'],
            ['read_only scope', { posthog_mcp_scopes: 'read_only' }, 'Read-only'],
            ['full scope', { posthog_mcp_scopes: 'full' }, 'Full (read-write)'],
        ])('%s', (_label, connectors, expected) => {
            expect(describePosthogAccess(connectors)).toBe(expected)
        })
    })
})
