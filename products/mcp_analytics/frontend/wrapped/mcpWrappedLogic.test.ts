import { initKeaTests } from '~/test/init'

import type { MCPWrappedApi } from '../generated/api.schemas'
import { CARD_DURATION_MS, mcpWrappedLogic } from './mcpWrappedLogic'

const WRAPPED = {
    year: 2026,
    generated_at: '2026-11-24T12:00:00Z',
    expires_at: '2026-12-08T12:00:00Z',
    cards: {
        intro: { tracked_since: '2026-07', server_count: 1 },
        tool_calls: { total_calls: 365, months: [{ month: '2026-07', calls: 365 }], growth_multiple: null },
        top_tools: { tools: [{ tool: 'get_forecast', calls: 270 }] },
        apps: null,
        labs: null,
        models: null,
        rush_hour: null,
        reliability: { success_rate: 0.92, most_reliable_tool: null, struggling_tool: null },
        speed: null,
        archetype: { archetype: 'one_hit_wonder', evidence: 0.74 },
    },
} as unknown as MCPWrappedApi

describe('mcpWrappedLogic', () => {
    let logic: ReturnType<typeof mcpWrappedLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        logic = mcpWrappedLogic()
        logic.mount()
        logic.actions.loadWrappedSuccess(WRAPPED)
        logic.actions.openStory('header_button')
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it.each([
        ['a pause', (paused: boolean) => logic.actions.setPaused(paused)],
        ['a hidden tab', (hidden: boolean) => logic.actions.setPageHidden(hidden)],
    ])('resumes after %s with the time the card had left', (_name, hold) => {
        jest.advanceTimersByTime(CARD_DURATION_MS - 1000)
        hold(true)
        jest.advanceTimersByTime(CARD_DURATION_MS * 3)
        expect(logic.values.cardIndex).toBe(0)

        hold(false)
        jest.advanceTimersByTime(999)
        expect(logic.values.cardIndex).toBe(0)
        jest.advanceTimersByTime(2)
        expect(logic.values.cardIndex).toBe(1)
    })
})
