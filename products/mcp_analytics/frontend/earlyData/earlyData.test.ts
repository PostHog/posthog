import { buildActivitySummary } from './activitySummary'
import { buildChecklist, EarlyStats } from './earlyDataChecklist'

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
        [{ totalCalls: 1, distinctClients: 1, errorCalls: 0, topTool: null }, /first tool call arrived/],
        [{ totalCalls: 4, distinctClients: 1, errorCalls: 1, topTool: 'search' }, /first 4 tool calls arrived/],
        // The full sentence composes favorite + failures with correct punctuation.
        [
            { totalCalls: 42, distinctClients: 3, errorCalls: 4, topTool: 'search_docs' },
            /^42 tool calls from 3 clients so far — search_docs is the favorite, 4 failures worth a look$/,
        ],
        // Failures read grammatically even without a favorite tool.
        [
            { totalCalls: 42, distinctClients: 0, errorCalls: 1, topTool: null },
            /^42 tool calls so far — 1 failure worth a look$/,
        ],
        [{ totalCalls: 42, distinctClients: 1, errorCalls: 0, topTool: null }, /^42 tool calls from 1 client so far$/],
    ])('summarizes %j', (input, expected) => {
        expect(buildActivitySummary(input)).toMatch(expected)
    })

    it.each([
        // Under 10 calls ratios are noise: hold judgment instead of warning.
        [stats({ totalCalls: 5, callsWithIntent: 0, distinctSessions: 5 }), 'pending', 'pending'],
        // Intent wired + sessions grouping: both healthy.
        [stats({ totalCalls: 40, callsWithIntent: 35, distinctSessions: 8 }), 'ok', 'ok'],
        // No intent + one session per call (stateless server): both warn.
        [stats({ totalCalls: 40, callsWithIntent: 2, distinctSessions: 40 }), 'warning', 'warning'],
        // 90% of calls being sessions is already degenerate, not just 100%.
        [stats({ totalCalls: 100, callsWithIntent: 90, distinctSessions: 90 }), 'ok', 'warning'],
    ])('checklist grades intent/sessions for %j as %s/%s', (input, intentStatus, sessionsStatus) => {
        const checklist = buildChecklist(input)
        expect(checklist.find((i) => i.key === 'intent')?.status).toBe(intentStatus)
        expect(checklist.find((i) => i.key === 'sessions')?.status).toBe(sessionsStatus)
    })

    it('flips unmet-demand reporting to ok once any report exists', () => {
        expect(buildChecklist(stats({})).find((i) => i.key === 'missing-capability')?.status).toBe('pending')
        expect(
            buildChecklist(stats({ missingCapabilityReports: 2 })).find((i) => i.key === 'missing-capability')?.status
        ).toBe('ok')
    })
})
