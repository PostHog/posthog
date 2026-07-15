import { initKeaTests } from '~/test/init'

import type { ToolStreamEvent } from '../types/streamTypes'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

function event(overrides: Partial<ToolStreamEvent> = {}): ToolStreamEvent {
    return {
        streamKey: 'run-1',
        toolCallId: 'tc-1',
        toolName: 'create_dashboard',
        rawToolName: 'exec',
        phase: 'started',
        // The invocation is opaque to the bus — a minimal cast is enough for matching tests.
        invocation: {} as ToolStreamEvent['invocation'],
        source: 'live',
        ...overrides,
    }
}

describe('toolStreamEventsLogic', () => {
    let logic: ReturnType<typeof toolStreamEventsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = toolStreamEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('delivers to matching listeners, honors `*`, and skips non-matches', () => {
        const named = jest.fn()
        const wildcard = jest.fn()
        const other = jest.fn()
        logic.actions.registerToolListener('named', { tools: ['create_dashboard'], onEvent: named })
        logic.actions.registerToolListener('wild', { tools: '*', onEvent: wildcard })
        logic.actions.registerToolListener('other', { tools: ['create_insight'], onEvent: other })

        logic.actions.emitToolEvent(event())

        expect(named).toHaveBeenCalledTimes(1)
        expect(wildcard).toHaveBeenCalledTimes(1)
        expect(other).not.toHaveBeenCalled()
    })

    it('suppresses replay events unless the subscription opts in via includeReplay', () => {
        const liveOnly = jest.fn()
        const withReplay = jest.fn()
        logic.actions.registerToolListener('live', { tools: '*', onEvent: liveOnly })
        logic.actions.registerToolListener('replay', { tools: '*', onEvent: withReplay, includeReplay: true })

        logic.actions.emitToolEvent(event({ source: 'replay' }))

        expect(liveOnly).not.toHaveBeenCalled()
        expect(withReplay).toHaveBeenCalledTimes(1)
    })

    it('stops delivering after deregister', () => {
        const cb = jest.fn()
        logic.actions.registerToolListener('x', { tools: '*', onEvent: cb })
        logic.actions.deregisterToolListener('x')
        logic.actions.emitToolEvent(event())
        expect(cb).not.toHaveBeenCalled()
    })
})
