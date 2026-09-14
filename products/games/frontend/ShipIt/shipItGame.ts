export const LANE_COUNT = 3
export const REQUIRED_APPROVALS = 2
export const STALENESS_LIMIT = 3
export const QUEUE_HOLD_MS = 8000
export const CONFLICT_PROGRESS_COST = 25
export const QUEUE_KICK_PROGRESS = 80

/** Items are hit when they reach the PR, which sits a little in from the left edge of the track. */
export const HIT_X = 0.08
const TRACK_SPEED_START = 0.28
const TRACK_SPEED_MAX = 0.58
const TRACK_SPEED_RAMP_MS = 60000
const SPAWN_INTERVAL_START_MS = 900
const SPAWN_INTERVAL_MIN_MS = 420
const SPAWN_RAMP_MS = 50000
const PROGRESS_MS_TO_FULL = 14000

export type ItemKind =
    | 'approval'
    | 'ci_green'
    | 'stamphog'
    | 'rebase'
    | 'trunk_merge'
    | 'conflict'
    | 'flake'
    | 'stale'
    | 'changes_requested'

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
    /** Index into LEVELS. Carries the score forward; everything else resets between levels. */
    level: number
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
    stamphog: { chip: 'stamphog', label: 'Stamped by stamphog', good: true },
    rebase: { chip: 'Rebase', label: 'Rebased onto master', good: true },
    trunk_merge: { chip: '/trunk merge', label: 'Enqueued with /trunk merge', good: true },
    conflict: { chip: 'Conflict', label: 'Merge conflict', good: false },
    flake: { chip: 'Flake', label: 'Flaky test', good: false },
    stale: { chip: 'Stale', label: 'Stale bot', good: false },
    changes_requested: { chip: 'Changes', label: 'Changes requested', good: false },
}

export interface Level {
    name: string
    /** One line under the level name, telling the player what changed. */
    goal: string
    kinds: ItemKind[]
    /** Multipliers on the base track speed and spawn interval. */
    speed: number
    spawn: number
    /** Whether reaching full progress enqueues on its own, or waits for a /trunk merge tile. */
    needsTrunkMerge: boolean
}

export const LEVELS: Level[] = [
    {
        name: 'Draft',
        goal: 'Get CI green and two approvals, then hold the queue.',
        kinds: ['approval', 'ci_green', 'conflict', 'flake', 'stale'],
        speed: 1,
        spawn: 1,
        needsTrunkMerge: false,
    },
    {
        name: 'Ready for review',
        goal: 'Reviewers can take approvals back, and a rebase costs you CI.',
        kinds: ['approval', 'ci_green', 'stamphog', 'rebase', 'conflict', 'flake', 'stale', 'changes_requested'],
        speed: 1.25,
        spawn: 0.8,
        needsTrunkMerge: false,
    },
    {
        name: 'Merge queue',
        goal: 'Nothing enqueues on its own. Catch a /trunk merge tile once you are ready.',
        kinds: [
            'approval',
            'ci_green',
            'stamphog',
            'rebase',
            'trunk_merge',
            'conflict',
            'flake',
            'stale',
            'changes_requested',
        ],
        speed: 1.5,
        spawn: 0.65,
        needsTrunkMerge: true,
    },
]

export const LAST_LEVEL = LEVELS.length - 1

const LANES = Array.from({ length: LANE_COUNT }, (_, index) => index)

export function levelOf(state: GameState): Level {
    return LEVELS[Math.min(LAST_LEVEL, state.level)]
}

function freshBoard(level: number, score: number): GameState {
    return {
        phase: 'coding',
        level,
        lane: 1,
        items: [],
        approvals: 0,
        ciGreen: false,
        progress: 0,
        staleness: 0,
        queueMs: 0,
        elapsedMs: 0,
        score,
        spawnTimerMs: 0,
        nextItemId: 1,
        lastEvent: null,
    }
}

export function createInitialState(): GameState {
    return freshBoard(0, 0)
}

/** Called after a merge on any level but the last. The score is the only thing that carries. */
export function advanceLevel(state: GameState): GameState {
    if (state.phase !== 'merged' || state.level >= LAST_LEVEL) {
        return state
    }
    return freshBoard(state.level + 1, state.score)
}

export function isMergeable(state: GameState): boolean {
    return state.ciGreen && state.approvals >= REQUIRED_APPROVALS
}

/**
 * True once the PR is only waiting for a /trunk merge tile to reach it. Mergeability is part of the
 * test because a flake can turn CI red at full progress, and the queue would refuse the pull request:
 * without this the spawner would keep offering the one tile that cannot help.
 */
export function isAwaitingQueue(state: GameState): boolean {
    return state.phase === 'coding' && state.progress >= 100 && levelOf(state).needsTrunkMerge && isMergeable(state)
}

export function isOver(state: GameState): boolean {
    return state.phase === 'closed' || (state.phase === 'merged' && state.level >= LAST_LEVEL)
}

function lerp(from: number, to: number, t: number): number {
    return from + (to - from) * Math.min(1, Math.max(0, t))
}

function trackSpeed(state: GameState): number {
    return lerp(TRACK_SPEED_START, TRACK_SPEED_MAX, state.elapsedMs / TRACK_SPEED_RAMP_MS) * levelOf(state).speed
}

function spawnInterval(state: GameState): number {
    return lerp(SPAWN_INTERVAL_START_MS, SPAWN_INTERVAL_MIN_MS, state.elapsedMs / SPAWN_RAMP_MS) * levelOf(state).spawn
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
    if (isOver(state) || state.phase === 'merged') {
        return state
    }
    const lane = Math.min(LANE_COUNT - 1, Math.max(0, state.lane + delta))
    return lane === state.lane ? state : { ...state, lane }
}

function applyItem(state: GameState, kind: ItemKind): GameState {
    if (state.phase === 'queued') {
        if (ITEMS[kind].good) {
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
        // The label exists to stand in for a missing required review, so it fills the whole bar at once.
        case 'stamphog':
            return {
                ...state,
                approvals: REQUIRED_APPROVALS,
                score: state.score + 75,
                lastEvent: 'Stamped by stamphog',
            }
        case 'ci_green':
            return { ...state, ciGreen: true, score: state.score + 25, lastEvent: 'CI passed' }
        case 'rebase':
            return {
                ...state,
                staleness: 0,
                ciGreen: false,
                score: state.score + 25,
                lastEvent: 'Rebased onto master, CI has to run again',
            }
        case 'trunk_merge':
            if (isMergeable(state) && state.progress >= 100) {
                return { ...state, phase: 'queued', queueMs: 0, score: state.score + 50, lastEvent: 'Enqueued' }
            }
            return {
                ...state,
                score: state.score + 10,
                lastEvent: 'The queue refused a pull request that is not ready',
            }
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
        case 'changes_requested':
            return { ...state, approvals: 0, lastEvent: 'A reviewer requested changes' }
    }
}

/**
 * Advance the game by one frame. Pure, so the caller owns both the clock and the randomness:
 * the scene passes real deltas and `Math.random`, tests pass fixed ones.
 */
export function step(state: GameState, dtMs: number, random: () => number): GameState {
    if (isOver(state) || state.phase === 'merged' || dtMs <= 0) {
        return state
    }

    let next: GameState = { ...state, elapsedMs: state.elapsedMs + dtMs }

    const speed = trackSpeed(next)
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
    const interval = spawnInterval(next)
    if (next.spawnTimerMs >= interval) {
        next.spawnTimerMs -= interval
        const kinds = levelOf(next).kinds
        const bad = random() < hazardShare(next)
        // Once the PR is only waiting to be enqueued, every helpful tile is the command that enqueues it.
        // Leaving it to chance would make the last stretch a wait rather than a run.
        const pool =
            isAwaitingQueue(next) && !bad
                ? ['trunk_merge' as ItemKind]
                : kinds.filter((kind) => ITEMS[kind].good !== bad)
        next.items = [
            ...next.items,
            {
                id: next.nextItemId,
                kind: pick(pool, random()),
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
        // The last level holds at full progress until a /trunk merge tile arrives, so the score stops
        // with the bar. Otherwise a player could wait there and collect for as long as they dodge.
        if (isMergeable(next) && next.progress < 100) {
            next.progress = Math.min(100, next.progress + (dtMs / PROGRESS_MS_TO_FULL) * 100)
            next.score += dtMs / 100
        }
        if (next.progress >= 100 && !levelOf(next).needsTrunkMerge) {
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
