import { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'

import { ApiSurveyClient } from './apiSurveyLogic'

export const exampleApiSurvey: Survey = {
    id: 'example-api-survey',
    name: 'Product feedback',
    type: SurveyType.API,
    start_date: '2026-01-01T00:00:00Z',
    end_date: null,
    feature_flag_keys: null,
    linked_flag_key: null,
    targeting_flag_key: null,
    internal_targeting_flag_key: null,
    appearance: null,
    conditions: null,
    current_iteration: null,
    current_iteration_start_date: null,
    questions: [
        { id: 'goal', type: SurveyQuestionType.Open, question: 'What were you trying to do, and what happened?' },
        {
            id: 'outcome',
            type: SurveyQuestionType.SingleChoice,
            question: 'Did you finish what you wanted to do?',
            choices: ['Yes', 'Partly', 'No'],
        },
        {
            id: 'usefulness',
            type: SurveyQuestionType.Rating,
            question: 'How useful was this?',
            display: 'number',
            scale: 5,
            lowerBoundLabel: 'Not useful',
            upperBoundLabel: 'Very useful',
            optional: true,
        },
        {
            id: 'improvements',
            type: SurveyQuestionType.MultipleChoice,
            question: 'What could improve?',
            choices: ['Clarity', 'Speed', 'Navigation'],
            optional: true,
        },
    ],
}

export function exampleSurveyClient(surveys: Survey[] = [exampleApiSurvey]): ApiSurveyClient {
    return {
        getSurveys: (callback) => callback(surveys),
        capture: () => ({ uuid: 'example-event' }) as ReturnType<ApiSurveyClient['capture']>,
        get_session_replay_url: () => 'https://example.com/replay',
    }
}
