import { initKeaTests } from '~/test/init'

import type { ToolStreamEvent } from '../types/streamTypes'
import { foregroundStreamLogic } from './foregroundStreamLogic'
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

    it('foregroundOnly delivers only events whose streamKey is the current foreground stream', () => {
        const cb = jest.fn()
        logic.actions.registerToolListener('fg', { tools: '*', foregroundOnly: true, onEvent: cb })

        // No foreground registered → an event for any stream is withheld.
        logic.actions.emitToolEvent(event({ streamKey: 'run-2' }))
        expect(cb).not.toHaveBeenCalled()

        // A different stream is foreground → still withheld.
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'p1')
        logic.actions.emitToolEvent(event({ streamKey: 'run-2' }))
        expect(cb).not.toHaveBeenCalled()

        // The event's own stream becomes foreground → the same event is now delivered.
        foregroundStreamLogic.actions.setForegroundStream('run-2', 'p1')
        logic.actions.emitToolEvent(event({ streamKey: 'run-2' }))
        expect(cb).toHaveBeenCalledTimes(1)
    })

    it('notifies onForegroundChange only when the foreground key actually changes', () => {
        const onChange = jest.fn()
        logic.actions.registerToolListener('fg-change', {
            tools: '*',
            onEvent: jest.fn(),
            onForegroundChange: onChange,
        })

        // A registration renewal with the same key is not a change.
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'p1')
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'p1')
        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenLastCalledWith('run-1')

        // A clear from a provider that isn't registered leaves the value untouched, so no notification.
        foregroundStreamLogic.actions.clearForegroundStream('p-stale')
        expect(onChange).toHaveBeenCalledTimes(1)

        foregroundStreamLogic.actions.setForegroundStream('run-2', 'p1')
        expect(onChange).toHaveBeenLastCalledWith('run-2')

        foregroundStreamLogic.actions.clearForegroundStream('p1')
        expect(onChange).toHaveBeenLastCalledWith(null)
        expect(onChange).toHaveBeenCalledTimes(3)
    })

    it('stops delivering after deregister', () => {
        const cb = jest.fn()
        logic.actions.registerToolListener('x', { tools: '*', onEvent: cb })
        logic.actions.deregisterToolListener('x')
        logic.actions.emitToolEvent(event())
        expect(cb).not.toHaveBeenCalled()
    })
})
