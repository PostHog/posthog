export const LANE_COUNT = 3
export const REQUIRED_APPROVALS = 2
export const STALENESS_LIMIT = 3
export const QUEUE_HOLD_MS = 8000
export const CONFLICT_PROGRESS_COST = 25
export const QUEUE_KICK_PROGRESS = 80

/** Items are hit when they reach the PR, which sits a little in from the left edge of the track. */
const HIT_X = 0.08
const TRACK_SPEED_START = 0.28
const TRACK_SPEED_MAX = 0.58
const TRACK_SPEED_RAMP_MS = 60000
const SPAWN_INTERVAL_START_MS = 900
const SPAWN_INTERVAL_MIN_MS = 420
const SPAWN_RAMP_MS = 50000
const PROGRESS_MS_TO_FULL = 14000

export type ItemKind = 'approval' | 'ci_green' | 'conflict' | 'flake' | 'stale'

export type Phase = 'coding' | 'queued' | 'merged' | 'closed'

export interface Item {
    id: number
    kind: ItemKind
    lane: number
    /** Position along the track, 1 at the spawn edge down to 0 at the PR. */
    x: number
}

export interface GameState {
    phase: Phase
    lane: number
    items: Item[]
    approvals: number
    ciGreen: boolean
    progress: number
    staleness: number
    queueMs: number
    elapsedMs: number
    score: number
    spawnTimerMs: number
    nextItemId: number
    /** Last thing that happened to the PR, shown as a status line. */
    lastEvent: string | null
}

/** One entry per item: the short name on the moving tile, the long one for the status line. */
export const ITEMS: Record<ItemKind, { chip: string; label: string; good: boolean }> = {
    approval: { chip: 'Approve', label: 'Approved', good: true },
    ci_green: { chip: 'CI pass', label: 'CI green', good: true },
    conflict: { chip: 'Conflict', label: 'Merge conflict', good: false },
    flake: { chip: 'Flake', label: 'Flaky test', good: false },
    stale: { chip: 'Stale', label: 'Stale bot', good: false },
}

const ITEM_KINDS = Object.keys(ITEMS) as ItemKind[]
const GOOD_ITEMS = ITEM_KINDS.filter((kind) => ITEMS[kind].good)
const BAD_ITEMS = ITEM_KINDS.filter((kind) => !ITEMS[kind].good)
const LANES = Array.from({ length: LANE_COUNT }, (_, index) => index)

export function createInitialState(): GameState {
    return {
        phase: 'coding',
        lane: 1,
        items: [],
        approvals: 0,
        ciGreen: false,
        progress: 0,
        staleness: 0,
        queueMs: 0,
        elapsedMs: 0,
        score: 0,
        spawnTimerMs: 0,
        nextItemId: 1,
        lastEvent: null,
    }
}

export function isMergeable(state: GameState): boolean {
    return state.ciGreen && state.approvals >= REQUIRED_APPROVALS
}

export function isOver(state: GameState): boolean {
    return state.phase === 'merged' || state.phase === 'closed'
}

function lerp(from: number, to: number, t: number): number {
    return from + (to - from) * Math.min(1, Math.max(0, t))
}

function trackSpeed(elapsedMs: number): number {
    return lerp(TRACK_SPEED_START, TRACK_SPEED_MAX, elapsedMs / TRACK_SPEED_RAMP_MS)
}

function spawnInterval(elapsedMs: number): number {
    return lerp(SPAWN_INTERVAL_START_MS, SPAWN_INTERVAL_MIN_MS, elapsedMs / SPAWN_RAMP_MS)
}

/** Hazards crowd out the helpful items as the run goes on, and the merge queue is hazards only. */
function hazardShare(state: GameState): number {
    if (state.phase === 'queued') {
        return 1
    }
    return lerp(0.4, 0.7, state.elapsedMs / SPAWN_RAMP_MS)
}

function pick<T>(options: T[], random: number): T {
    return options[Math.min(options.length - 1, Math.floor(random * options.length))]
}

export function moveLane(state: GameState, delta: number): GameState {
    if (isOver(state)) {
        return state
    }
    const lane = Math.min(LANE_COUNT - 1, Math.max(0, state.lane + delta))
    return lane === state.lane ? state : { ...state, lane }
}

function applyItem(state: GameState, kind: ItemKind): GameState {
    if (state.phase === 'queued') {
        if (GOOD_ITEMS.includes(kind)) {
            return { ...state, score: state.score + 25, lastEvent: `${ITEMS[kind].label} while queued` }
        }
        return {
            ...state,
            phase: 'coding',
            progress: QUEUE_KICK_PROGRESS,
            queueMs: 0,
            ciGreen: false,
            lastEvent: `Kicked out of the merge queue by ${ITEMS[kind].label.toLowerCase()}`,
        }
    }

    switch (kind) {
        case 'approval':
            return {
                ...state,
                approvals: Math.min(REQUIRED_APPROVALS, state.approvals + 1),
                score: state.score + 25,
                lastEvent: 'Approved',
            }
        case 'ci_green':
            return { ...state, ciGreen: true, score: state.score + 25, lastEvent: 'CI passed' }
        case 'conflict':
            return {
                ...state,
                progress: Math.max(0, state.progress - CONFLICT_PROGRESS_COST),
                ciGreen: false,
                lastEvent: 'Merge conflict, rebase and rerun CI',
            }
        case 'flake':
            return { ...state, ciGreen: false, lastEvent: 'A flaky test went red' }
        case 'stale':
            return {
                ...state,
                staleness: state.staleness + 1,
                approvals: Math.max(0, state.approvals - 1),
                lastEvent: 'Stale bot dismissed a review',
            }
    }
}

/**
 * Advance the game by one frame. Pure, so the caller owns both the clock and the randomness:
 * the scene passes real deltas and `Math.random`, tests pass fixed ones.
 */
export function step(state: GameState, dtMs: number, random: () => number): GameState {
    if (isOver(state) || dtMs <= 0) {
        return state
    }

    let next: GameState = { ...state, elapsedMs: state.elapsedMs + dtMs }

    const speed = trackSpeed(next.elapsedMs)
    const moved: Item[] = []
    for (const item of next.items) {
        const x = item.x - speed * (dtMs / 1000)
        if (x <= HIT_X) {
            if (item.lane === next.lane) {
                next = applyItem(next, item.kind)
            }
            continue
        }
        moved.push({ ...item, x })
    }
    next.items = moved

    next.spawnTimerMs += dtMs
    const interval = spawnInterval(next.elapsedMs)
    if (next.spawnTimerMs >= interval) {
        next.spawnTimerMs -= interval
        const bad = random() < hazardShare(next)
        next.items = [
            ...next.items,
            {
                id: next.nextItemId,
                kind: pick(bad ? BAD_ITEMS : GOOD_ITEMS, random()),
                lane: pick(LANES, random()),
                x: 1,
            },
        ]
        next.nextItemId += 1
    }

    if (next.staleness >= STALENESS_LIMIT) {
        return { ...next, phase: 'closed', lastEvent: 'Closed as stale' }
    }

    if (next.phase === 'coding') {
        if (isMergeable(next)) {
            next.progress = Math.min(100, next.progress + (dtMs / PROGRESS_MS_TO_FULL) * 100)
            next.score += dtMs / 100
        }
        if (next.progress >= 100) {
            next.phase = 'queued'
            next.queueMs = 0
            next.lastEvent = 'Enqueued'
        }
    } else if (next.phase === 'queued') {
        next.queueMs += dtMs
        if (next.queueMs >= QUEUE_HOLD_MS) {
            next.phase = 'merged'
            next.score += 500
            next.lastEvent = 'Merged'
        }
    }

    return next
}
