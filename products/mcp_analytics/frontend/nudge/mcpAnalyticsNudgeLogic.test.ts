import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mcpAnalyticsNudgeLogic } from './mcpAnalyticsNudgeLogic'

describe('mcpAnalyticsNudgeLogic', () => {
    let logic: ReturnType<typeof mcpAnalyticsNudgeLogic.build>
    let toolCallDefinitions: { id: string; name: string }[]
    let infoSpy: jest.SpyInstance
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        localStorage.clear()
        toolCallDefinitions = []
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/': () => [
                    200,
                    { count: toolCallDefinitions.length, results: toolCallDefinitions },
                ],
            },
        })
        initKeaTests()
        infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast-id')
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic = mcpAnalyticsNudgeLogic()
        logic.mount()
    })

    afterEach(() => {
        infoSpy.mockRestore()
        captureSpy.mockRestore()
    })

    it.each([
        ['shows the nudge when the project has no tool calls', false, 1],
        ['skips the nudge when the project already collects tool calls', true, 0],
    ])('%s', async (_, hasToolCalls, expectedToasts) => {
        if (hasToolCalls) {
            toolCallDefinitions = [{ id: '1', name: '$mcp_tool_call' }]
        }
        logic.actions.maybeShowNudge('insight')
        await expectLogic(logic).toFinishAllListeners()
        expect(infoSpy).toHaveBeenCalledTimes(expectedToasts)
        expect(captureSpy.mock.calls.filter(([event]) => event === 'mcp analytics nudge shown')).toEqual(
            expectedToasts ? [['mcp analytics nudge shown', { surface: 'insight' }]] : []
        )
    })

    it('shows the nudge only once per project', async () => {
        logic.actions.maybeShowNudge('insight')
        logic.actions.maybeShowNudge('dashboard')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.maybeShowNudge('dashboard')
        await expectLogic(logic).toFinishAllListeners()
        expect(infoSpy).toHaveBeenCalledTimes(1)
    })
})
