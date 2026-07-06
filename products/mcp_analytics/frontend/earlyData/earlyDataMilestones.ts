import { FULL_DASHBOARD_LIFETIME_CALLS, KEY_METRICS_LIFETIME_CALLS } from '../mcpAnalyticsOnboardingLogic'

export interface Milestone {
    key: string
    /** Lifetime tool calls needed to reach this milestone. */
    threshold: number
    /** What this milestone unlocks, in user-facing copy. */
    unlocks: string
    reached: boolean
}

/**
 * The early-data milestone ladder. Each step names what becomes meaningful at that
 * volume, so the waiting period reads as progress rather than emptiness. Thresholds
 * are heuristics for when each view stops looking sparse, not hard feature gates —
 * everything below the graduation threshold is visible from the first call.
 */
export function buildMilestones(toolCallsTotal: number): Milestone[] {
    const ladder: Array<Pick<Milestone, 'key' | 'threshold' | 'unlocks'>> = [
        { key: 'first-call', threshold: 1, unlocks: 'Live activity feed' },
        { key: 'tool-patterns', threshold: 25, unlocks: 'Tool usage and error patterns' },
        { key: 'sessions', threshold: 100, unlocks: 'Session timelines and intent summaries' },
        { key: 'key-metrics', threshold: KEY_METRICS_LIFETIME_CALLS, unlocks: 'Key metrics and charts' },
        { key: 'full-dashboard', threshold: FULL_DASHBOARD_LIFETIME_CALLS, unlocks: 'Full dashboard' },
    ]
    return ladder.map((m) => ({ ...m, reached: toolCallsTotal >= m.threshold }))
}

export function nextMilestone(milestones: Milestone[]): Milestone | null {
    return milestones.find((m) => !m.reached) ?? null
}

/**
 * Progress toward the next milestone, measured from the previous one so the bar
 * visibly restarts and refills at each step instead of crawling toward the
 * graduation threshold for weeks.
 */
export function progressToNextMilestone(toolCallsTotal: number, milestones: Milestone[]): number {
    const next = nextMilestone(milestones)
    if (!next) {
        return 1
    }
    const previousThreshold = milestones.filter((m) => m.reached).at(-1)?.threshold ?? 0
    const span = next.threshold - previousThreshold
    if (span <= 0) {
        return 1
    }
    return Math.min(1, Math.max(0, (toolCallsTotal - previousThreshold) / span))
}
