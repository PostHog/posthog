import posthog, { Survey, SurveyType, SurveyQuestionType } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT, MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'
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
                type: SurveyQuestionType.Rating,
                question: 'Was this useful?',
                display: 'emoji',
                scale: 2,
                lowerBoundLabel: '',
                upperBoundLabel: '',
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
            contextKey: 'example-session',
            isImpersonated: false,
            prompt: MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT,
        })
        unmount = logic.mount()
    })

    afterEach(() => {
        unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it.each([false, true])(
        'waits for matching surveys and a fresh reading delay (backgrounded: %s)',
        (backgrounded) => {
            jest.mocked(posthog.displaySurvey).mockClear()
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            expect(logic.values.visible).toBe(false)
            loadSurvey(false)
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            expect(logic.values.visible).toBe(false)
            loadSurvey()
            if (backgrounded) {
                jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS / 2)
                const hidden = jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
                document.dispatchEvent(new Event('visibilitychange'))
                jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS * 2)
                expect(logic.values.visible).toBe(false)
                expect(logic.values.lastPromptAt).toBe(0)
                expect(posthog.capture).not.toHaveBeenCalledWith('survey shown', expect.anything())
                hidden.mockReturnValue(false)
                document.dispatchEvent(new Event('visibilitychange'))
            }
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS - 1)
            expect(logic.values.visible).toBe(false)
            jest.advanceTimersByTime(1)
            expect(logic.values.visible).toBe(true)
            expect(posthog.capture).toHaveBeenCalledWith(
                'survey shown',
                expect.objectContaining({
                    feedback_surface: 'mcp_analytics',
                    feedback_entry_point: 'session_review_prompt',
                    mcp_analytics_tab: 'sessions',
                    $survey_id: survey.id,
                    $survey_submission_id: expect.any(String),
                })
            )
            expect(posthog.displaySurvey).not.toHaveBeenCalled()
            loadSurvey()
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            expect(jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'survey shown')).toHaveLength(1)
        }
    )

    it.each(['complete', 'dismiss'] as const)(
        'captures the displayed copy and placement throughout a %s submission',
        (ending) => {
            unmount()
            const prompt = {
                entryPoint: 'tool_review_prompt',
                tab: 'tools',
                version: 2,
                question: 'Did this tool breakdown help you find what you needed?',
                followUpQuestion: 'What did you find, or what was missing?',
            }
            logic = mcpAnalyticsFeedbackLogic({
                userId: 'example-user',
                contextKey: 'example-tool',
                isImpersonated: false,
                prompt,
            })
            unmount = logic.mount()
            loadSurvey()
            jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
            expect(logic.values.prompt).toEqual(prompt)
            const displayedQuestion = prompt.question
            prompt.question = 'Later copy must not change an open prompt'
            logic.actions.submitResponse('1', false)
            if (ending === 'complete') {
                logic.actions.setDetail('Found a slow call.')
                logic.actions.submitResponse('1', true)
            } else {
                logic.actions.dismissPrompt()
            }
            const events = jest.mocked(posthog.capture).mock.calls
            expect(events.map(([name]) => name)).toEqual([
                'survey shown',
                'survey sent',
                ending === 'complete' ? 'survey sent' : 'survey dismissed',
            ])
            for (const [, properties] of events) {
                expect(properties).toMatchObject({
                    $survey_id: survey.id,
                    $survey_submission_id: logic.values.submissionId,
                    feedback_surface: 'mcp_analytics',
                    feedback_entry_point: 'tool_review_prompt',
                    mcp_analytics_tab: 'tools',
                    feedback_question_version: 2,
                    feedback_question: displayedQuestion,
                    feedback_followup_question: prompt.followUpQuestion,
                    $survey_questions: [
                        { id: 'example-choice', question: displayedQuestion },
                        { id: 'example-detail', question: prompt.followUpQuestion },
                    ],
                })
            }
            expect(logic.values.prompt.question).toBe(displayedQuestion)
            expect(survey.questions[0].question).toBe('Was this useful?')
        }
    )

    it('keeps the cooldown across placements after dismissal', () => {
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        logic.actions.dismissPrompt()
        expect(logic.values.visible).toBe(false)
        unmount()
        logic = mcpAnalyticsFeedbackLogic({
            userId: 'example-user',
            contextKey: 'another-session',
            isImpersonated: false,
            prompt: { ...MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT, entryPoint: 'tool_review_prompt', tab: 'tools' },
        })
        unmount = logic.mount()
        loadSurvey()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        unmount()
        jest.advanceTimersByTime(FEEDBACK_PROMPT_COOLDOWN_MS)
        logic = mcpAnalyticsFeedbackLogic({
            userId: 'example-user',
            contextKey: 'example-session',
            isImpersonated: false,
            prompt: MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT,
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
        { userId: '', contextKey: 'example-session', isImpersonated: false },
        { userId: 'example-user', contextKey: 'example-session', isImpersonated: true },
    ])('does not prompt an ineligible user: %j', (props) => {
        unmount()
        logic = mcpAnalyticsFeedbackLogic({ ...props, prompt: MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT })
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
            logic.actions.submitResponse('2', false)
            logic.actions.submitResponse('1', false)
            expect(logic.values.answer).toBe('2')
            expect(posthog.capture).toHaveBeenCalledWith(
                'survey sent',
                expect.objectContaining({
                    $survey_id: survey.id,
                    $survey_completed: false,
                    '$survey_response_example-choice': '2',
                })
            )
            const submissionId = logic.values.submissionId
            logic.actions.setDetail(detail)
            logic.actions.submitResponse('2', true)
            logic.actions.submitResponse('2', true)
            expect(logic.values.completed).toBe(true)
            expect(logic.values.submitting).toBe(false)
            const sent = jest.mocked(posthog.capture).mock.calls.filter(([name]) => name === 'survey sent')
            expect(sent).toHaveLength(2)
            expect(sent[1][1]).toEqual(
                expect.objectContaining({
                    $survey_submission_id: submissionId,
                    $survey_completed: true,
                    '$survey_response_example-choice': '2',
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
        logic.actions.submitResponse('2', false)
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
            logic.actions.submitResponse('1', false)
            logic.actions.setDetail('Found the slow call.')
            const submissionId = logic.values.submissionId
            jest.mocked(posthog.capture).mockImplementationOnce(() => {
                if (failure === 'thrown') {
                    throw new Error('capture failed')
                }
                return undefined
            })
            logic.actions.submitResponse('1', true)
            expect(logic.values).toMatchObject({
                error: true,
                completed: false,
                submitting: false,
                detail: 'Found the slow call.',
            })
            logic.actions.submitResponse('1', true)
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
        {
            questions: [
                { ...survey.questions[0], type: SurveyQuestionType.SingleChoice, choices: ['Yes', 'No'] },
                survey.questions[1],
            ],
        },
        { questions: [{ ...survey.questions[0], scale: 5 as const }, survey.questions[1]] },
        { questions: [survey.questions[0], { ...survey.questions[1], optional: false }] },
    ])('does not show a stopped or incompatible survey: %j', (overrides) => {
        logic.actions.schedulePrompt({ ...survey, ...overrides })
        jest.advanceTimersByTime(FEEDBACK_PROMPT_DELAY_MS)
        expect(logic.values.visible).toBe(false)
        expect(posthog.capture).not.toHaveBeenCalled()
    })
})
