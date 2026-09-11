import posthog, { Survey } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { MCP_ANALYTICS_FEEDBACK_PROPERTIES, MCP_ANALYTICS_FEEDBACK_SURVEY_ID } from './constants'
import {
    FEEDBACK_PROMPT_COOLDOWN_MS,
    FEEDBACK_PROMPT_DELAY_MS,
    mcpAnalyticsFeedbackLogic,
} from './mcpAnalyticsFeedbackLogic'

describe('mcpAnalyticsFeedbackLogic', () => {
    let logic: ReturnType<typeof mcpAnalyticsFeedbackLogic.build>
    let surveysLoaded: Parameters<typeof posthog.onSurveysLoaded>[0]
    let unmount: () => void

    const loadSurvey = (available = true): void => {
        surveysLoaded(
            available ? [{ id: MCP_ANALYTICS_FEEDBACK_SURVEY_ID, start_date: '2026-01-01T00:00:00Z' } as Survey] : [],
            { isLoaded: true }
        )
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-01T12:00:00Z'))
        localStorage.clear()
        initKeaTests(false)
        jest.mocked(posthog.capture).mockClear()
        jest.mocked(posthog.onSurveysLoaded).mockImplementation((callback) => {
            surveysLoaded = callback
            return () => {}
        })
        logic = mcpAnalyticsFeedbackLogic({
            userId: 'example-user',
            sessionId: 'example-session',
            isImpersonated: false,
        })
        unmount = logic.mount()
    })

    afterEach(() => {
        unmount()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    it('waits for the running survey and reading delay, then records one invitation without opening the survey', () => {
        jest.mocked(posthog.displaySurvey).mockClear()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        loadSurvey(false)
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS - 1)
        expect(logic.values.visible).toBe(false)
        jest.advanceTimersByTime(1)
        expect(logic.values.visible).toBe(true)
        expect(posthog.capture).toHaveBeenCalledWith(
            'mcp analytics feedback prompt shown',
            MCP_ANALYTICS_FEEDBACK_PROPERTIES
        )
        expect(posthog.displaySurvey).not.toHaveBeenCalled()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(jest.mocked(posthog.capture).mock.calls.filter(([name]) => name.endsWith('prompt shown'))).toHaveLength(
            1
        )
    })

    it.each(['dismissPrompt', 'openSurvey'] as const)('keeps the cooldown across sessions after %s', (action) => {
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        logic.actions[action]()
        expect(logic.values.visible).toBe(false)
        unmount()
        logic = mcpAnalyticsFeedbackLogic({
            userId: 'example-user',
            sessionId: 'another-session',
            isImpersonated: false,
        })
        unmount = logic.mount()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        unmount()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_COOLDOWN_MS)
        logic = mcpAnalyticsFeedbackLogic({
            userId: 'example-user',
            sessionId: 'example-session',
            isImpersonated: false,
        })
        unmount = logic.mount()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(true)
    })

    it('cancels a pending invitation when leaving the session detail', () => {
        loadSurvey()
        unmount()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(posthog.capture).not.toHaveBeenCalledWith('mcp analytics feedback prompt shown', expect.anything())
        unmount = () => {}
    })

    it.each([
        { userId: '', sessionId: 'example-session', isImpersonated: false },
        { userId: 'example-user', sessionId: 'example-session', isImpersonated: true },
    ])('does not prompt an ineligible user: %j', (props) => {
        unmount()
        logic = mcpAnalyticsFeedbackLogic(props)
        unmount = logic.mount()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
    })
})
