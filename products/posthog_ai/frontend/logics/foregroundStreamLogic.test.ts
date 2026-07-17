import { initKeaTests } from '~/test/init'

import { foregroundStreamLogic } from './foregroundStreamLogic'

describe('foregroundStreamLogic', () => {
    let logic: ReturnType<typeof foregroundStreamLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = foregroundStreamLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // Two surfaces overlap during a mount/unmount race: provider p1 registers, p2 registers, then p1's
    // late unmount fires clearForegroundStream('p1'). The clear is provider-scoped, so it leaves p2's
    // registration intact — an unconditional clear would blank the foreground and silently disable
    // apply-back for the run the user is actually watching.
    it('a stale clear from a replaced surface does not clobber the newer registration', () => {
        logic.actions.setForegroundStream('A', 'p1')
        logic.actions.setForegroundStream('B', 'p2')
        expect(logic.values.foregroundStreamKey).toBe('B')

        logic.actions.clearForegroundStream('p1')
        expect(logic.values.foregroundStreamKey).toBe('B')

        logic.actions.clearForegroundStream('p2')
        expect(logic.values.foregroundStreamKey).toBeNull()
    })

    // Co-mounted surfaces (side panel + full-page run view) hold independent registrations: both keys
    // gate permissions, apply-back targets the most recent, and closing one surface falls back to the
    // other instead of leaving no foreground — the case the old single-slot model got wrong.
    it('co-mounted surfaces register independently and fall back on clear', () => {
        logic.actions.setForegroundStream('A', 'p1')
        logic.actions.setForegroundStream('B', 'p2')
        expect(logic.values.foregroundStreamKeys).toEqual(new Set(['A', 'B']))
        expect(logic.values.foregroundStreamKey).toBe('B')

        logic.actions.clearForegroundStream('p2')
        expect(logic.values.foregroundStreamKeys).toEqual(new Set(['A']))
        expect(logic.values.foregroundStreamKey).toBe('A')
    })

    // A surface switching runs re-registers under the same provider: the old key must drop out of the
    // gate set (or a stale run would keep prompting) and the new key must win the apply-back slot.
    it('same-provider re-registration replaces the previous key', () => {
        logic.actions.setForegroundStream('A', 'p1')
        logic.actions.setForegroundStream('B', 'p1')
        expect(logic.values.foregroundStreamKeys).toEqual(new Set(['B']))
        expect(logic.values.foregroundStreamKey).toBe('B')
    })
})
