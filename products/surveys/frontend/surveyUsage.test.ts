import posthog from 'posthog-js'

import { Survey, SurveyQuestionType, SurveyType } from '~/types'

import { reportSurveyCreated, reportSurveyEdited } from './surveyUsage'

describe('surveyUsage', () => {
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
    it.each([
        { isDuplicate: undefined, creationSource: undefined, expectedDuplicate: false, expectedSource: 'full_editor' },
        { isDuplicate: true, creationSource: 'wizard' as const, expectedDuplicate: true, expectedSource: 'wizard' },
    ])(
        'reports survey creation with source $expectedSource',
        ({ isDuplicate, creationSource, expectedDuplicate, expectedSource }) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            const survey = {
                id: 'survey-example',
                name: 'Example survey',
                type: SurveyType.Popover,
                linked_insight_id: null,
                questions: [{ type: SurveyQuestionType.Open, question: 'Private question' }],
                conditions: null,
                iteration_count: null,
                iteration_frequency_days: null,
                appearance: null,
                enable_partial_responses: false,
            } as Survey

            reportSurveyCreated(survey, isDuplicate, creationSource)

            expect(capture).toHaveBeenCalledWith('survey created', {
                source: 'web',
                name: 'Example survey',
                id: 'survey-example',
                survey_type: SurveyType.Popover,
                questions_length: 1,
                question_types: [SurveyQuestionType.Open],
                is_duplicate: expectedDuplicate,
                creation_source: expectedSource,
                linked_insight_id: null,
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
        }
    )
})
