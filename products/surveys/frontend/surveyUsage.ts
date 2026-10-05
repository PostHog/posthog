import posthog from 'posthog-js'

import { MultipleSurveyQuestion, Survey, SurveyQuestionType } from '~/types'

type SurveyEditedProperties = {
    name: Survey['name']
    id: Survey['id']
    created_at: Survey['created_at']
    start_date: Survey['start_date']
    events_count: number | undefined
    recurring_survey_iteration_count: number
    recurring_survey_iteration_interval: number
    shuffle_questions_enabled: boolean
    shuffle_question_options_enabled_count: number
    has_branching_logic: boolean
    has_partial_responses: Survey['enable_partial_responses']
    skipping_submit_button: boolean
}

function getSurveyEditedProperties(survey: Survey): SurveyEditedProperties {
    const questionsWithShuffledOptions = survey.questions.filter((question) => {
        return question.hasOwnProperty('shuffleOptions') && (question as MultipleSurveyQuestion).shuffleOptions
    })

    return {
        name: survey.name,
        id: survey.id,
        created_at: survey.created_at,
        start_date: survey.start_date,
        events_count: survey.conditions?.events?.values.length,
        recurring_survey_iteration_count: survey.iteration_count == undefined ? 0 : survey.iteration_count,
        recurring_survey_iteration_interval:
            survey.iteration_frequency_days == undefined ? 0 : survey.iteration_frequency_days,
        shuffle_questions_enabled: !!survey.appearance?.shuffleQuestions,
        shuffle_question_options_enabled_count: questionsWithShuffledOptions.length,
        has_branching_logic: survey.questions.some(
            (question) => question.branching && Object.keys(question.branching).length > 0
        ),
        has_partial_responses: survey.enable_partial_responses,
        skipping_submit_button: survey.questions.some((question) => {
            if (
                question.type === SurveyQuestionType.SingleChoice ||
                question.type === SurveyQuestionType.MultipleChoice
            ) {
                return question.skipSubmitButton
            }
            return false
        }),
    }
}

export function reportSurveyEdited(survey: Survey): void {
    posthog.capture('survey edited', getSurveyEditedProperties(survey))
}
