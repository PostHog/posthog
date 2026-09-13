import {
    createInitialState,
    GameState,
    isOver,
    Item,
    ItemKind,
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

    it('ignores an item in another lane', () => {
        const state = stateWith({ lane: 0, items: [itemAt('approval', 2)] })

        expect(step(state, 100, noHits).approvals).toBe(0)
    })
})
