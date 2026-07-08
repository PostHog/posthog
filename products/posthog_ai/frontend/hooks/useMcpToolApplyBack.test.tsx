import { act, cleanup, renderHook } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { foregroundStreamLogic } from '../logics/foregroundStreamLogic'
import { toolStreamEventsLogic } from '../logics/toolStreamEventsLogic'
import type { ToolStreamEvent } from '../types/streamTypes'
import { useMcpToolApplyBack } from './useMcpToolApplyBack'

function toolEvent(
    command: string,
    toolCallId: string,
    phase: ToolStreamEvent['phase'] = 'completed'
): ToolStreamEvent {
    return {
        streamKey: 'run-1',
        toolCallId,
        toolName: 'create_insight',
        rawToolName: 'exec',
        phase,
        invocation: {
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command },
        } as unknown as ToolStreamEvent['invocation'],
        source: 'live',
    }
}

describe('useMcpToolApplyBack', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        cleanup()
    })

    // The core terminal-mode contract: it buffers the last matching completion, applies it at the end
    // of a persistent run's turn, and falls back to run termination when no turn-complete frame arrives.
    // Regressions here caused completed execute-sql calls to stay buffered forever on persistent runs.
    it('applies the last matching completion at foreground turn or run completion', () => {
        const onApply = jest.fn()
        renderHook(() => useMcpToolApplyBack({ tools: ['create_insight'], onApply }))

        // Not the foreground stream yet → completions are withheld and turn completion flushes nothing.
        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(toolEvent('call create_insight {"name":"early"}', 'early'))
            toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: 'run-1' })
        })
        expect(onApply).not.toHaveBeenCalled()

        // Register run-1 as the foreground stream (its own act so the reset effect flushes first).
        act(() => {
            foregroundStreamLogic.actions.setForegroundStream('run-1')
        })

        // Two matching completions arrive; the later one supersedes the earlier.
        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(toolEvent('call create_insight {"name":"first"}', 'a'))
            toolStreamEventsLogic.actions.emitToolEvent(toolEvent('call create_insight {"name":"second"}', 'b'))
        })
        // Nothing applies until the persistent run finishes this turn.
        expect(onApply).not.toHaveBeenCalled()

        act(() => {
            toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: 'run-1' })
        })
        expect(onApply).toHaveBeenCalledTimes(1)
        expect(onApply.mock.calls[0][0].toolCallId).toBe('b')
        expect(onApply.mock.calls[0][1].innerInput).toEqual({ name: 'second' })

        // A later turn is a fresh buffer. Run termination still flushes it if the adapter omits
        // turn-complete while shutting down.
        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(toolEvent('call create_insight {"name":"third"}', 'c'))
            toolStreamEventsLogic.actions.emitRunLifecycleEvent({ streamKey: 'run-1', status: 'completed' })
        })
        expect(onApply).toHaveBeenCalledTimes(2)
        expect(onApply.mock.calls[1][0].toolCallId).toBe('c')
        expect(onApply.mock.calls[1][1].innerInput).toEqual({ name: 'third' })
    })

    it('applies tool-call-completed mode before turn end', () => {
        const onApply = jest.fn()
        renderHook(() => useMcpToolApplyBack({ tools: ['create_insight'], onApply, applyOn: 'tool_call_completed' }))
        act(() => {
            foregroundStreamLogic.actions.setForegroundStream('run-1')
        })

        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(
                toolEvent('call create_insight {"name":"first"}', 'a', 'updated')
            )
        })
        expect(onApply).not.toHaveBeenCalled()

        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(toolEvent('call create_insight {"name":"first"}', 'a'))
        })
        expect(onApply).toHaveBeenCalledTimes(1)
        expect(onApply.mock.calls[0][0].phase).toBe('completed')
        expect(onApply.mock.calls[0][1].innerInput).toEqual({ name: 'first' })

        act(() => {
            toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: 'run-1' })
        })
        expect(onApply).toHaveBeenCalledTimes(1)
    })
})
