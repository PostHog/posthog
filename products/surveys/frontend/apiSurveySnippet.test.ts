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

const snippet = (surveyId: string, responses: string): string => `posthog.getActiveMatchingSurveys((surveys) => {
    const survey = surveys.find((s) => s.id === '${surveyId}')
    if (!survey) return
    const surveyProperties = {
        $survey_id: survey.id,
        $survey_iteration: survey.current_iteration,
    }
    posthog.capture('survey shown', surveyProperties)

    // Render your own UI and call these from its handlers
    const onSubmit = () =>
        posthog.capture('survey sent', {
            ...surveyProperties,
            $survey_submission_id: crypto.randomUUID(),
            $survey_completed: true,
            $survey_questions: survey.questions.map(({ id, question }) => ({ id, question })),${responses}
        })
    const onDismiss = () => posthog.capture('survey dismissed', surveyProperties)
})`

describe('buildApiSurveySnippet', () => {
    it.each<[string, Partial<Survey | NewSurvey>, string]>([
        [
            'saved survey with open text and multiple choice questions',
            { id: 'abc', questions: [openQuestion, choiceQuestion] as SurveyQuestion[] },
            snippet(
                'abc',
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
                `
            // Why?
            '$survey_response_<question id>': 'Your answer',`
            ),
        ],
        [
            'rating, single choice with escaped characters, and link questions',
            {
                id: 'abc',
                questions: [
                    {
                        id: 'q-1',
                        type: SurveyQuestionType.Rating,
                        scale: 10,
                        question: 'How likely are you to recommend us to a friend or colleague who builds products?',
                    },
                    { id: 'q-2', type: SurveyQuestionType.SingleChoice, question: 'Pick', choices: ["It's a\\b"] },
                    { id: 'q-3', type: SurveyQuestionType.Link, question: 'Book a call', link: 'https://example.com' },
                ] as SurveyQuestion[],
            },
            snippet(
                'abc',
                `
            // How likely are you to recommend us to a friend or colleague...
            '$survey_response_q-1': '10',
            // Pick
            '$survey_response_q-2': 'It\\'s a\\\\b',
            // Book a call
            '$survey_response_q-3': 'Your answer',`
            ),
        ],
    ])('%s', (_name, survey, expected) => {
        expect(buildApiSurveySnippet(survey as Survey)).toEqual(expected)
    })
})
