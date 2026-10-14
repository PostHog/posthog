import { truncate } from 'lib/utils/strings'
import { NewSurvey } from 'scenes/surveys/constants'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import { Survey, SurveyEventName, SurveyEventProperties, SurveyQuestion, SurveyQuestionType } from '~/types'

const UNSAVED_SURVEY_ID = '<survey id>'
const UNSAVED_QUESTION_ID = '<question id>'
const QUESTION_COMMENT_MAX_LENGTH = 60

const quote = (value: string): string =>
    `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n')}'`

const firstChoice = (question: SurveyQuestion, fallback: string): string =>
    quote(('choices' in question && question.choices[0]) || fallback)

const textAnswer = (): string => quote('Your answer')

const ANSWER_PLACEHOLDERS: Record<SurveyQuestionType, (question: SurveyQuestion) => string> = {
    [SurveyQuestionType.Open]: textAnswer,
    [SurveyQuestionType.Link]: textAnswer,
    [SurveyQuestionType.Rating]: (question) => quote(String('scale' in question ? question.scale : 5)),
    [SurveyQuestionType.SingleChoice]: (question) => firstChoice(question, 'Your answer'),
    [SurveyQuestionType.MultipleChoice]: (question) => `[${firstChoice(question, 'Option 1')}]`,
}

function responseLines(question: SurveyQuestion): string[] {
    const key = getSurveyIdBasedResponseKey(question.id ?? UNSAVED_QUESTION_ID)
    const comment = truncate(question.question.replace(/\s+/g, ' ').trim(), QUESTION_COMMENT_MAX_LENGTH)
    return [`    // ${comment}`, `    ${quote(key)}: ${ANSWER_PLACEHOLDERS[question.type](question)},`]
}

export function buildApiSurveySnippet(survey: Survey | NewSurvey): string {
    const id = survey.id && survey.id !== 'new' ? survey.id : UNSAVED_SURVEY_ID
    const quotedId = quote(id)
    const iterationSuffix = survey.current_iteration ? `/${survey.current_iteration}` : ''

    return [
        'posthog.getActiveMatchingSurveys((surveys) => {',
        `    const survey = surveys.find((s) => s.id === ${quotedId})`,
        '    if (!survey) return',
        '    // Render your own UI, then:',
        `    posthog.capture(${quote(SurveyEventName.SHOWN)}, { ${SurveyEventProperties.SURVEY_ID}: ${quotedId} })`,
        '})',
        '',
        '// When the user submits',
        `posthog.capture(${quote(SurveyEventName.SENT)}, {`,
        `    ${SurveyEventProperties.SURVEY_ID}: ${quotedId},`,
        `    ${SurveyEventProperties.SURVEY_SUBMISSION_ID}: crypto.randomUUID(),`,
        `    ${SurveyEventProperties.SURVEY_COMPLETED}: true,`,
        ...survey.questions.flatMap(responseLines),
        `    $set: { ${quote(`$survey_responded/${id}${iterationSuffix}`)}: true },`,
        '})',
        '',
        '// When the user closes the survey without answering',
        `posthog.capture(${quote(SurveyEventName.DISMISSED)}, { ${SurveyEventProperties.SURVEY_ID}: ${quotedId} })`,
    ].join('\n')
}
