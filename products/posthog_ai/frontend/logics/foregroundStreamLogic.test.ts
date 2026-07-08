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

    // Two surfaces overlap during a mount/unmount race: A registers, B registers, then A's late unmount
    // fires clearForegroundStream('A'). The clear must be key-checked so it leaves B's registration
    // intact — an unconditional clear would blank the foreground and silently disable apply-back for the
    // run the user is actually watching.
    it('a stale clear from a replaced surface does not clobber the newer registration', () => {
        logic.actions.setForegroundStream('A')
        logic.actions.setForegroundStream('B')
        expect(logic.values.foregroundStreamKey).toBe('B')

        logic.actions.clearForegroundStream('A')
        expect(logic.values.foregroundStreamKey).toBe('B')

        logic.actions.clearForegroundStream('B')
        expect(logic.values.foregroundStreamKey).toBeNull()
    })
})
