// The app holds itself to the published API rate limits for these endpoints. The buckets hold 25% of each budget: they
// exist to stop a client bug, such as a refresh loop, and normal use never empties them. They live in memory, so a cold
// start refills them.

export type BudgetFamily = 'insights' | 'dashboards' | 'query' | 'replay'

interface BucketSpec {
    capacity: number
    windowMs: number
}

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS

/** Published budgets: insights 240/min and 1,200/h; dashboards and shortcuts 480/min and 4,800/h; query 240/min and 1,200/h. */
export const BUDGETS: Record<BudgetFamily, readonly BucketSpec[]> = {
    insights: [
        { capacity: 60, windowMs: MINUTE_MS },
        { capacity: 300, windowMs: HOUR_MS },
    ],
    dashboards: [
        { capacity: 120, windowMs: MINUTE_MS },
        { capacity: 1200, windowMs: HOUR_MS },
    ],
    query: [
        { capacity: 60, windowMs: MINUTE_MS },
        { capacity: 300, windowMs: HOUR_MS },
    ],
    // The session timeline also posts to `query/`, on buckets of its own, so heavy Views use never empties them.
    replay: [
        { capacity: 60, windowMs: MINUTE_MS },
        { capacity: 300, windowMs: HOUR_MS },
    ],
}

interface Bucket {
    tokens: number
    updatedAt: number
}

const buckets = new Map<BudgetFamily, Bucket[]>()

function bucketsFor(family: BudgetFamily, now: number): Bucket[] {
    let state = buckets.get(family)
    if (!state) {
        state = BUDGETS[family].map((spec) => ({ tokens: spec.capacity, updatedAt: now }))
        buckets.set(family, state)
    }
    BUDGETS[family].forEach((spec, index) => {
        const bucket = state[index]
        if (bucket) {
            const refill = ((now - bucket.updatedAt) * spec.capacity) / spec.windowMs
            bucket.tokens = Math.min(spec.capacity, bucket.tokens + Math.max(0, refill))
            bucket.updatedAt = now
        }
    })
    return state
}

/** True when a request of this family could go out now. Takes no token. */
export function canSpend(family: BudgetFamily, now: number = Date.now()): boolean {
    return bucketsFor(family, now).every((bucket) => bucket.tokens >= 1)
}

/** Takes one token from every bucket of the family, or none when any bucket is empty. */
export function trySpend(family: BudgetFamily, now: number = Date.now()): boolean {
    const state = bucketsFor(family, now)
    if (!state.every((bucket) => bucket.tokens >= 1)) {
        return false
    }
    for (const bucket of state) {
        bucket.tokens -= 1
    }
    return true
}

export function resetBudgets(): void {
    buckets.clear()
}

const FAMILY_PATH = /^\/api\/(?:projects|environments)\/[^/]+\/(insights|dashboards|file_system_shortcut|query)(?:\/|$)/

/** The budget a project path counts against, or null for endpoints outside the Views budgets. */
export function budgetFamilyFor(path: string): BudgetFamily | null {
    const match = FAMILY_PATH.exec(path)
    switch (match?.[1]) {
        case 'insights':
            return 'insights'
        case 'dashboards':
        case 'file_system_shortcut':
            return 'dashboards'
        case 'query':
            return 'query'
        default:
            return null
    }
}

export class BudgetExceededError extends Error {
    readonly family: BudgetFamily

    constructor(family: BudgetFamily) {
        super('The app paused updates for a moment. Try again in a minute.')
        this.name = 'BudgetExceededError'
        this.family = family
    }
}
