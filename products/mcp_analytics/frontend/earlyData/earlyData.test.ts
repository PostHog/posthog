import { buildActivitySummary } from './activitySummary'
import { EarlyStats, buildNextSteps } from './nextSteps'

const stats = (overrides: Partial<EarlyStats>): EarlyStats => ({
    totalCalls: 0,
    distinctTools: 0,
    distinctSessions: 0,
    distinctClients: 0,
    callsWithIntent: 0,
    errorCalls: 0,
    missingCapabilityReports: 0,
    ...overrides,
})

describe('early data derivations', () => {
    it.each([
        // First calls get the celebratory copy, not a stats sentence.
        [
            { lifetimeCalls: 1, totalCalls: 1, distinctClients: 1, errorCalls: 0, topTool: null },
            /first tool call arrived/,
            null,
        ],
        [
            { lifetimeCalls: 4, totalCalls: 4, distinctClients: 1, errorCalls: 1, topTool: 'search' },
            /first 4 tool calls arrived/,
            '1 failure',
        ],
        [
            { lifetimeCalls: 25_000_000, totalCalls: 0, distinctClients: 0, errorCalls: 0, topTool: null },
            /^No tool calls in the last 30 days$/,
            null,
        ],
        [
            { lifetimeCalls: null, totalCalls: 0, distinctClients: 0, errorCalls: 0, topTool: null },
            /^No tool calls in the last 30 days$/,
            null,
        ],
        [
            { lifetimeCalls: null, totalCalls: 4, distinctClients: 1, errorCalls: 0, topTool: null },
            /^4 tool calls in the last 30 days from 1 client$/,
            null,
        ],
        [
            { lifetimeCalls: 3, totalCalls: 4, distinctClients: 1, errorCalls: 0, topTool: null },
            /^Your first 4 tool calls arrived/,
            null,
        ],
        // The failure count is its own phrase so the view can render it as a feed filter.
        [
            { lifetimeCalls: 25_000_000, totalCalls: 42, distinctClients: 3, errorCalls: 4, topTool: 'search_docs' },
            /^42 tool calls in the last 30 days from 3 clients\. search_docs is the favorite$/,
            '4 failures',
        ],
        // Big client and failure counts get thousands separators, unlike the abbreviated call count.
        [
            {
                lifetimeCalls: 25_000_000,
                totalCalls: 21_700_000,
                distinctClients: 1051,
                errorCalls: 533_638,
                topTool: 'execute-sql',
            },
            /^21\.7M tool calls in the last 30 days from 1,051 clients\. execute-sql is the favorite$/,
            '533,638 failures',
        ],
        [
            { lifetimeCalls: 42, totalCalls: 42, distinctClients: 0, errorCalls: 1, topTool: null },
            /^42 tool calls in the last 30 days$/,
            '1 failure',
        ],
    ])('summarizes %j', (input, headline, failures) => {
        const summary = buildActivitySummary(input)
        expect(summary.headline).toMatch(headline)
        expect(summary.failures).toBe(failures)
    })

    it.each([
        // Under 10 calls ratios are noise: no instrumentation nag yet.
        [stats({ totalCalls: 5, callsWithIntent: 0, distinctSessions: 5 }), false, []],
        // Everything wired and an alert in place: nothing to do, so the row disappears.
        [stats({ totalCalls: 40, callsWithIntent: 35, distinctSessions: 8, errorCalls: 3 }), true, []],
        // No intent + stateless sessions + failures without an alert: priority order.
        [
            stats({ totalCalls: 40, callsWithIntent: 2, distinctSessions: 40, errorCalls: 3 }),
            false,
            ['intent', 'notification', 'sessions'],
        ],
        // Calls without any session ID need conversation IDs as much as one-session-per-call does.
        [stats({ totalCalls: 40, callsWithIntent: 35, distinctSessions: 0 }), true, ['sessions']],
        // 90% of calls being sessions is already degenerate, not just 100%.
        [stats({ totalCalls: 100, callsWithIntent: 90, distinctSessions: 90 }), true, ['sessions']],
        // Failures never prompt an alert while the count is still unknown.
        [stats({ totalCalls: 40, callsWithIntent: 35, distinctSessions: 8, errorCalls: 3 }), null, []],
        [stats({ totalCalls: 40, callsWithIntent: 35, distinctSessions: 8, errorCalls: 3 }), false, ['notification']],
    ])('picks next steps for %j with notification=%s', (input, hasFailureNotification, expectedKeys) => {
        expect(buildNextSteps(input, hasFailureNotification).map((step) => step.key)).toEqual(expectedKeys)
    })

    it('hands instrumentation steps to an agent and product steps to a link', () => {
        const steps = buildNextSteps(
            stats({ totalCalls: 40, callsWithIntent: 0, distinctSessions: 8, errorCalls: 1 }),
            false
        )

        expect(steps.map((step) => [step.key, step.action.kind])).toEqual([
            ['intent', 'agent-prompt'],
            ['notification', 'link'],
        ])
        expect(steps[0].action).toMatchObject({
            prompt: expect.stringContaining('posthog.com/docs/mcp-analytics/intent'),
            docsUrl: expect.stringContaining('posthog.com/docs/mcp-analytics/intent'),
        })
        expect(steps[1].action).toMatchObject({ to: '/mcp-analytics/notifications' })
    })
})
