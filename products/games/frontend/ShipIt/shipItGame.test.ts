import {
    advanceLevel,
    createInitialState,
    GameState,
    isAwaitingQueue,
    isOver,
    Item,
    ItemKind,
    LAST_LEVEL,
    QUEUE_HOLD_MS,
    QUEUE_KICK_PROGRESS,
    REQUIRED_APPROVALS,
    STALENESS_LIMIT,
    step,
} from './shipItGame'

/** Spawns a helpful item in the last lane, so a player in lane 0 is never touched by a spawn. */
const noHits = (): number => 0.99

function stateWith(overrides: Partial<GameState>): GameState {
    return { ...createInitialState(), ...overrides }
}

function itemAt(kind: ItemKind, lane: number): Item {
    return { id: 1, kind, lane, x: 0.09 }
}

/** Long enough that an item from itemAt travels past the hit line in a single step. */
const FRAME_MS = 100

function run(state: GameState, steps: number, random: () => number = noHits): GameState {
    let current = state
    for (let i = 0; i < steps && !isOver(current); i++) {
        current = step(current, 16, random)
    }
    return current
}

describe('shipItGame', () => {
    it.each([
        ['CI green and enough approvals', true, REQUIRED_APPROVALS, true],
        ['CI red but enough approvals', false, REQUIRED_APPROVALS, false],
        ['CI green but too few approvals', true, REQUIRED_APPROVALS - 1, false],
        ['CI red and too few approvals', false, 0, false],
    ])('progresses only with %s', (_label, ciGreen, approvals, expectedToProgress) => {
        const after = run(stateWith({ lane: 0, ciGreen, approvals }), 60)

        expect(after.progress > 0).toBe(expectedToProgress)
    })

    it('reaches merged on an uninterrupted run', () => {
        const after = run(stateWith({ lane: 0, ciGreen: true, approvals: REQUIRED_APPROVALS }), 2000)

        expect(after.phase).toBe('merged')
    })

    it('closes the pull request once the stale bot hits its limit', () => {
        const state = stateWith({ lane: 1, staleness: STALENESS_LIMIT - 1, items: [itemAt('stale', 1)] })

        expect(step(state, 100, noHits).phase).toBe('closed')
    })

    it('kicks a queued pull request back to coding instead of merging it', () => {
        const state = stateWith({ phase: 'queued', progress: 100, lane: 1, ciGreen: true, items: [itemAt('flake', 1)] })

        const after = step(state, 100, noHits)

        expect(after.phase).toBe('coding')
        expect(after.progress).toBe(QUEUE_KICK_PROGRESS)
    })

    // The frame the hold completes on is the only one where the two outcomes compete, so it is the
    // frame that pins the order: a hazard has to be collected before the timer is read.
    it.each([
        ['a hazard arrives on the completing frame', [itemAt('flake', 1)], 'coding'],
        ['the lane is clear on the completing frame', [], 'merged'],
    ])('%s', (_label, items, expectedPhase) => {
        const state = stateWith({
            phase: 'queued',
            progress: 100,
            lane: 1,
            ciGreen: true,
            approvals: REQUIRED_APPROVALS,
            queueMs: QUEUE_HOLD_MS - FRAME_MS,
            items,
        })

        expect(step(state, FRAME_MS, noHits).phase).toBe(expectedPhase)
    })

    it('stays queued on the frame before the hold completes', () => {
        const state = stateWith({
            phase: 'queued',
            progress: 100,
            lane: 1,
            ciGreen: true,
            approvals: REQUIRED_APPROVALS,
            queueMs: QUEUE_HOLD_MS - FRAME_MS * 2,
        })

        expect(step(state, FRAME_MS, noHits).phase).toBe('queued')
    })

    it('ignores an item in another lane', () => {
        const state = stateWith({ lane: 0, items: [itemAt('approval', 2)] })

        expect(step(state, 100, noHits).approvals).toBe(0)
    })

    it.each([
        ['a middle level', 0, false],
        ['the last level', LAST_LEVEL, true],
    ])('merging ends the run only on %s', (_label, level, expectedToEnd) => {
        const merged = stateWith({ level, phase: 'merged' })

        expect(isOver(merged)).toBe(expectedToEnd)
    })

    it('carries the score into the next level and resets the board', () => {
        const merged = stateWith({
            level: 0,
            phase: 'merged',
            score: 900,
            ciGreen: true,
            approvals: REQUIRED_APPROVALS,
            progress: 100,
            staleness: 2,
            items: [itemAt('stale', 1)],
        })

        const next = advanceLevel(merged)

        expect(next.level).toBe(1)
        expect(next.score).toBe(900)
        expect(next.phase).toBe('coding')
        expect(next.ciGreen).toBe(false)
        expect(next.approvals).toBe(0)
        expect(next.progress).toBe(0)
        expect(next.staleness).toBe(0)
        expect(next.items).toEqual([])
    })

    it('holds the last level at full progress until a /trunk merge arrives', () => {
        const ready = stateWith({ level: LAST_LEVEL, lane: 0, ciGreen: true, approvals: REQUIRED_APPROVALS })

        const waiting = run(ready, 2000)
        expect(waiting.progress).toBe(100)
        expect(waiting.phase).toBe('coding')

        const held = run(waiting, 500)
        expect(held.score).toBe(waiting.score)

        const enqueued = step({ ...waiting, lane: 1, items: [itemAt('trunk_merge', 1)] }, 100, noHits)
        expect(enqueued.phase).toBe('queued')
    })

    it('stops forcing /trunk merge tiles while CI is red, so the level cannot stall', () => {
        const ready = stateWith({
            level: LAST_LEVEL,
            progress: 100,
            ciGreen: true,
            approvals: REQUIRED_APPROVALS,
        })

        expect(isAwaitingQueue(ready)).toBe(true)
        expect(isAwaitingQueue({ ...ready, ciGreen: false })).toBe(false)
    })

    it.each([
        ['stamphog fills the approvals a missing review left', 'stamphog' as ItemKind, 0, REQUIRED_APPROVALS],
        ['changes requested takes them all back', 'changes_requested' as ItemKind, REQUIRED_APPROVALS, 0],
    ])('%s', (_label, kind, approvals, expected) => {
        const state = stateWith({ level: 1, lane: 1, approvals, items: [itemAt(kind, 1)] })

        expect(step(state, 100, noHits).approvals).toBe(expected)
    })

    it('clears staleness on a rebase but sends CI back to red', () => {
        const state = stateWith({ level: 1, lane: 1, staleness: 2, ciGreen: true, items: [itemAt('rebase', 1)] })

        const after = step(state, 100, noHits)

        expect(after.staleness).toBe(0)
        expect(after.ciGreen).toBe(false)
    })
})
