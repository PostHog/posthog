import { buildChecklist, EarlyStats } from './earlyDataChecklist'
import { buildMilestones, nextMilestone, progressToNextMilestone } from './earlyDataMilestones'

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
        // Boundaries: exactly at a threshold counts as reached; progress restarts at 0
        // toward the next step and never goes negative or above 1.
        [0, 'first-call', 0],
        [1, 'tool-patterns', 0],
        [13, 'tool-patterns', 0.5],
        [25, 'sessions', 0],
        [999, 'full-dashboard', (999 - 300) / 700],
        [1000, null, 1],
        [5000, null, 1],
    ])('at %i calls the next milestone is %s with progress %f', (calls, expectedNextKey, expectedProgress) => {
        const milestones = buildMilestones(calls)
        expect(nextMilestone(milestones)?.key ?? null).toBe(expectedNextKey)
        expect(progressToNextMilestone(calls, milestones)).toBeCloseTo(expectedProgress, 5)
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
