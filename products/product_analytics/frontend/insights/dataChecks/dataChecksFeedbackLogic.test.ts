import posthog, { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    DATA_CHECKS_FEEDBACK_RATINGS,
    DATA_CHECKS_FEEDBACK_SURVEY_ID,
    dataChecksFeedbackLogic,
} from './dataChecksFeedbackLogic'

describe('dataChecksFeedbackLogic', () => {
    const survey: Survey = {
        id: DATA_CHECKS_FEEDBACK_SURVEY_ID,
        name: 'Insight data checks usefulness',
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
                id: 'example-rating',
                type: SurveyQuestionType.Rating,
                question: 'Were these checks useful?',
                display: 'emoji',
                scale: 2,
                lowerBoundLabel: '',
                upperBoundLabel: '',
            },
            {
                id: 'example-note',
                type: SurveyQuestionType.Open,
                question: 'What would make it better?',
                optional: true,
            },
        ],
    }

    const mountWithSurveys = (surveys: Survey[]): ReturnType<typeof dataChecksFeedbackLogic.build> => {
        posthog.getActiveMatchingSurveys = jest.fn((callback) => callback(surveys))
        const logic = dataChecksFeedbackLogic({ userId: 'example-user' })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests(false)
        jest.mocked(posthog.onSurveysLoaded).mockImplementation(() => () => {})
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            callback([], {})
            return () => {}
        })
        jest.mocked(posthog.capture).mockClear()
    })

    it.each([
        { name: 'no live survey', surveys: [], visible: false },
        { name: 'another survey', surveys: [{ ...survey, id: 'another-survey' }], visible: false },
        { name: 'its survey', surveys: [survey], visible: true },
    ])('shows the prompt only while its survey is live for the person: $name', ({ surveys, visible }) => {
        expect(mountWithSurveys(surveys).values.visible).toBe(visible)
    })

    it('counts a rating and its note as one response', () => {
        const logic = mountWithSurveys([survey])

        logic.actions.rate(DATA_CHECKS_FEEDBACK_RATINGS.NOT_USEFUL)
        logic.actions.setNote('  Slow on big charts  ')
        logic.actions.submitNote()

        const sent = jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'survey sent')
        expect(sent.map(([, properties]) => properties)).toEqual([
            expect.objectContaining({
                $survey_id: DATA_CHECKS_FEEDBACK_SURVEY_ID,
                $survey_submission_id: logic.values.submissionId,
                $survey_completed: false,
                '$survey_response_example-rating': '2',
            }),
            expect.objectContaining({
                $survey_submission_id: logic.values.submissionId,
                $survey_completed: true,
                '$survey_response_example-rating': '2',
                '$survey_response_example-note': 'Slow on big charts',
            }),
        ])
    })

    it.each(['rate', 'dismiss'] as const)('stops asking after the person chooses to %s', (choice) => {
        const logic = mountWithSurveys([survey])
        if (choice === 'rate') {
            logic.actions.rate(DATA_CHECKS_FEEDBACK_RATINGS.USEFUL)
        } else {
            logic.actions.dismiss()
        }
        logic.unmount()

        expect(mountWithSurveys([survey]).values.visible).toBe(false)
    })
})
