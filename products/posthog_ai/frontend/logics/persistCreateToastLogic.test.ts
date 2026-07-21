import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import type { ToolStreamEvent } from '../types/streamTypes'
import { foregroundStreamLogic } from './foregroundStreamLogic'
import { persistCreateToastLogic } from './persistCreateToastLogic'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

function completedCreate(toolName: string, output: unknown, streamKey = 'run-1'): ToolStreamEvent {
    return {
        streamKey,
        toolCallId: 'tc-1',
        toolName,
        rawToolName: 'exec',
        phase: 'completed',
        invocation: { output } as unknown as ToolStreamEvent['invocation'],
        source: 'live',
    }
}

describe('persistCreateToastLogic', () => {
    let successSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests(false)
        successSpy = jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast-id')
        persistCreateToastLogic.mount()
    })

    afterEach(() => {
        persistCreateToastLogic.unmount()
        successSpy.mockRestore()
    })

    // Foreground gating + fire-once + id parsing in one pass: a background completion is silent, the
    // foreground one toasts exactly once with the entity name and an "Open …" link. Regressions in any of
    // these (toasting background runs, double-toasting, dropping the link) slip past the bus-level tests.
    it('toasts once for a completed foreground create and stays silent for a background run', () => {
        toolStreamEventsLogic.actions.emitToolEvent(completedCreate('dashboard-create', { id: 7, name: 'Growth' }))
        expect(successSpy).not.toHaveBeenCalled()

        foregroundStreamLogic.actions.setForegroundStream('run-1')
        toolStreamEventsLogic.actions.emitToolEvent(completedCreate('dashboard-create', { id: 7, name: 'Growth' }))

        expect(successSpy).toHaveBeenCalledTimes(1)
        expect(successSpy.mock.calls[0][0]).toContain('Growth')
        expect(successSpy.mock.calls[0][1]?.button?.label).toBe('Open dashboard')
    })
})
