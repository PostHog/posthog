import posthog from 'posthog-js'

import { Survey, SurveyQuestionType } from '~/types'

import { reportSurveyEdited } from './surveyUsage'

describe('reportSurveyEdited', () => {
    it('reports survey configuration without question text or responses', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const survey = {
            id: 'survey-example',
            name: 'Example survey',
            created_at: '2026-01-01T00:00:00Z',
            start_date: null,
            questions: [{ type: SurveyQuestionType.Open, question: 'Private question' }],
            conditions: null,
            iteration_count: null,
            iteration_frequency_days: null,
            appearance: null,
            enable_partial_responses: false,
        } as Survey

        reportSurveyEdited(survey)

        expect(capture).toHaveBeenCalledWith('survey edited', {
            name: 'Example survey',
            id: 'survey-example',
            created_at: '2026-01-01T00:00:00Z',
            start_date: null,
            events_count: undefined,
            recurring_survey_iteration_count: 0,
            recurring_survey_iteration_interval: 0,
            shuffle_questions_enabled: false,
            shuffle_question_options_enabled_count: 0,
            has_branching_logic: false,
            has_partial_responses: false,
            skipping_submit_button: false,
        })
        capture.mockRestore()
    })
})
