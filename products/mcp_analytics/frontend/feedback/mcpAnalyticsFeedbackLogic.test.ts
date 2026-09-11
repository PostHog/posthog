import posthog, { Survey, SurveyType, SurveyQuestionType } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { MCP_ANALYTICS_FEEDBACK_PROPERTIES, MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'
import {
    FEEDBACK_PROMPT_COOLDOWN_MS,
    FEEDBACK_PROMPT_DELAY_MS,
    mcpAnalyticsFeedbackLogic,
} from './mcpAnalyticsFeedbackLogic'

describe('mcpAnalyticsFeedbackLogic', () => {
    let logic: ReturnType<typeof mcpAnalyticsFeedbackLogic.build>
    let surveysLoaded: Parameters<typeof posthog.onSurveysLoaded>[0]
    let unmount: () => void

    const survey: Survey = {
        id: MCP_ANALYTICS_USEFULNESS_SURVEY_ID,
        name: 'Session usefulness',
        type: SurveyType.API,
        start_date: '2026-01-01T00:00:00Z',
        feature_flag_keys: null,
        linked_flag_key: null,
        targeting_flag_key: null,
        internal_targeting_flag_key: null,
        appearance: null,
        conditions: null,
        end_date: null,
        current_iteration: null,
        current_iteration_start_date: null,
        questions: [
            {
                id: 'example-choice',
                type: SurveyQuestionType.SingleChoice,
                question: 'Was this useful?',
                choices: ['Yes', 'Partly', 'No'],
            },
            { id: 'example-detail', type: SurveyQuestionType.Open, question: 'What did you learn?', optional: true },
        ],
    }

    const loadSurvey = (available = true): void => {
        jest.mocked(posthog.getActiveMatchingSurveys).mockImplementation((callback) =>
            callback(available ? [survey] : [])
        )
        surveysLoaded(available ? [survey] : [], { isLoaded: true })
    }

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-01T12:00:00Z'))
        localStorage.clear()
        crypto.randomUUID = () => '00000000-0000-4000-8000-000000000001'
        initKeaTests(false)
        posthog.is_capturing = jest.fn(() => true)
        posthog.getActiveMatchingSurveys = jest.fn((callback) => callback([]))
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            callback([], {})
            return () => {}
        })
        jest.mocked(posthog.capture).mockClear()
        jest.mocked(posthog.capture).mockReturnValue({ uuid: 'example-event' } as ReturnType<typeof posthog.capture>)
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
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it('waits for matching surveys and the reading delay, then records one impression', () => {
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
            'survey shown',
            expect.objectContaining({
                ...MCP_ANALYTICS_FEEDBACK_PROPERTIES,
                $survey_id: survey.id,
                $survey_submission_id: expect.any(String),
            })
        )
        expect(posthog.displaySurvey).not.toHaveBeenCalled()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'survey shown')).toHaveLength(1)
    })

    it('keeps the cooldown across sessions after dismissal', () => {
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        logic.actions.dismissPrompt()
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
        expect(posthog.capture).not.toHaveBeenCalledWith('survey shown', expect.anything())
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
    it.each(['', 'Found a failed tool call.'])(
        'keeps the first answer and optional detail in one submission: %j',
        (detail) => {
            loadSurvey()
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            logic.actions.submitResponse('Partly', false)
            logic.actions.submitResponse('Yes', false)
            expect(logic.values.answer).toBe('Partly')
            expect(posthog.capture).toHaveBeenCalledWith(
                'survey sent',
                expect.objectContaining({
                    $survey_id: survey.id,
                    $survey_completed: false,
                    '$survey_response_example-choice': 'Partly',
                })
            )
            const submissionId = logic.values.submissionId
            logic.actions.setDetail(detail)
            logic.actions.submitResponse('Partly', true)
            logic.actions.submitResponse('Partly', true)
            expect(logic.values.completed).toBe(true)
            expect(logic.values.submitting).toBe(false)
            const sent = jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'survey sent')
            expect(sent).toHaveLength(2)
            expect(sent[1][1]).toEqual(
                expect.objectContaining({
                    $survey_submission_id: submissionId,
                    $survey_completed: true,
                    '$survey_response_example-choice': 'Partly',
                    ...(detail ? { '$survey_response_example-detail': detail } : {}),
                })
            )
            logic.actions.dismissPrompt()
            expect(posthog.capture).not.toHaveBeenCalledWith('survey dismissed', expect.anything())
        }
    )

    it('preserves an answered question when dismissed before the optional follow-up', () => {
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        logic.actions.submitResponse('No', false)
        logic.actions.dismissPrompt()
        expect(posthog.capture).toHaveBeenCalledWith(
            'survey dismissed',
            expect.objectContaining({
                $survey_submission_id: logic.values.submissionId,
                $survey_partially_completed: true,
            })
        )
        expect(jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'survey sent')).toHaveLength(1)
    })

    it.each(['dropped', 'thrown'] as const)(
        'allows retry when capture is %s without losing optional text',
        (failure) => {
            loadSurvey()
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            logic.actions.submitResponse('Yes', false)
            logic.actions.setDetail('Found the slow call.')
            const submissionId = logic.values.submissionId
            jest.mocked(posthog.capture).mockImplementationOnce(() => {
                if (failure === 'thrown') {
                    throw new Error('capture failed')
                }
                return undefined
            })
            logic.actions.submitResponse('Yes', true)
            expect(logic.values).toMatchObject({
                error: true,
                completed: false,
                submitting: false,
                detail: 'Found the slow call.',
            })
            logic.actions.submitResponse('Yes', true)
            expect(logic.values).toMatchObject({ error: false, completed: true, submissionId })
        }
    )

    it('cancels the pending prompt when targeting changes and skips users without capture', () => {
        loadSurvey()
        loadSurvey(false)
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        jest.mocked(posthog.is_capturing).mockReturnValue(false)
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
    })
    it.each([
        { start_date: null },
        { end_date: '2026-08-01T00:00:00Z' },
        { type: SurveyType.Popover },
        { questions: [] },
        { questions: [survey.questions[0], { ...survey.questions[1], optional: false }] },
    ])('does not show a stopped or incompatible survey: %j', (overrides) => {
        logic.actions.schedulePrompt({ ...survey, ...overrides })
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        expect(posthog.capture).not.toHaveBeenCalled()
    })
})
