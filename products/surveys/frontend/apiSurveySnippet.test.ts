import { NewSurvey } from 'scenes/surveys/constants'

import { Survey, SurveyQuestion, SurveyQuestionType } from '~/types'

import { buildApiSurveySnippet } from './apiSurveySnippet'

const openQuestion = { id: 'q-1', type: SurveyQuestionType.Open, question: 'What do you think?' }
const choiceQuestion = {
    id: 'q-2',
    type: SurveyQuestionType.MultipleChoice,
    question: "Which features do you use?\n  It's a long one",
    choices: ['Option 1', "Option 2's"],
}

const snippet = (
    surveyId: string,
    setKey: string,
    responses: string
): string => `posthog.getActiveMatchingSurveys((surveys) => {
    const survey = surveys.find((s) => s.id === '${surveyId}')
    if (!survey) return
    // Render your own UI, then:
    posthog.capture('survey shown', { $survey_id: '${surveyId}' })
})

// When the user submits
posthog.capture('survey sent', {
    $survey_id: '${surveyId}',
    $survey_submission_id: crypto.randomUUID(),
    $survey_completed: true,${responses}
    $set: { '${setKey}': true },
})

// When the user closes the survey without answering
posthog.capture('survey dismissed', { $survey_id: '${surveyId}' })`

describe('buildApiSurveySnippet', () => {
    it.each<[string, Partial<Survey | NewSurvey>, string]>([
        [
            'saved survey with open text and multiple choice questions',
            { id: 'abc', questions: [openQuestion, choiceQuestion] as SurveyQuestion[] },
            snippet(
                'abc',
                '$survey_responded/abc',
                `
    // What do you think?
    '$survey_response_q-1': 'Your answer',
    // Which features do you use? It's a long one
    '$survey_response_q-2': ['Option 1'],`
            ),
        ],
        [
            'unsaved survey with an unsaved question',
            { id: 'new', questions: [{ type: SurveyQuestionType.Open, question: 'Why?' }] as SurveyQuestion[] },
            snippet(
                '<survey id>',
                '$survey_responded/<survey id>',
                `
    // Why?
    '$survey_response_<question id>': 'Your answer',`
            ),
        ],
        [
            'survey in its second iteration',
            { id: 'abc', current_iteration: 2, questions: [] },
            snippet('abc', '$survey_responded/abc/2', ''),
        ],
        [
            'rating question with a long text and an escaped single choice',
            {
                id: 'abc',
                questions: [
                    {
                        id: 'q-1',
                        type: SurveyQuestionType.Rating,
                        scale: 10,
                        question: 'How likely are you to recommend us to a friend or colleague who builds products?',
                    },
                    { id: 'q-2', type: SurveyQuestionType.SingleChoice, question: 'Pick', choices: ["It's fine"] },
                ] as SurveyQuestion[],
            },
            snippet(
                'abc',
                '$survey_responded/abc',
                `
    // How likely are you to recommend us to a friend or colleague...
    '$survey_response_q-1': '10',
    // Pick
    '$survey_response_q-2': 'It\\'s fine',`
            ),
        ],
    ])('%s', (_name, survey, expected) => {
        expect(buildApiSurveySnippet(survey as Survey)).toEqual(expected)
    })
})
