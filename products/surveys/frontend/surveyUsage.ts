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

type SurveyConfigurationProperties = Omit<SurveyEditedProperties, 'name' | 'id' | 'created_at' | 'start_date'>

type SurveyCreationSource = 'form_builder' | 'full_editor' | 'llm_analytics' | 'quick_create' | 'template' | 'wizard'

type SurveyCreatedProperties = SurveyConfigurationProperties & {
    source: 'web'
    name: Survey['name']
    id: Survey['id']
    survey_type: Survey['type']
    questions_length: number
    question_types: SurveyQuestionType[]
    is_duplicate: boolean
    creation_source: SurveyCreationSource
    linked_insight_id: Survey['linked_insight_id']
}

function getSurveyConfigurationProperties(survey: Survey): SurveyConfigurationProperties {
    const questionsWithShuffledOptions = survey.questions.filter((question) => {
        return question.hasOwnProperty('shuffleOptions') && (question as MultipleSurveyQuestion).shuffleOptions
    })

    return {
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

function getSurveyEditedProperties(survey: Survey): SurveyEditedProperties {
    return {
        name: survey.name,
        id: survey.id,
        created_at: survey.created_at,
        start_date: survey.start_date,
        ...getSurveyConfigurationProperties(survey),
    }
}

function getSurveyCreatedProperties(
    survey: Survey,
    isDuplicate?: boolean,
    creationSource?: SurveyCreationSource
): SurveyCreatedProperties {
    return {
        // The web app is the only place this event is emitted from — there is no backend
        // equivalent — so stamping the surface here is what puts surveys in a `source`
        // breakdown at all, rather than showing up as unattributed.
        source: 'web',
        name: survey.name,
        id: survey.id,
        survey_type: survey.type,
        questions_length: survey.questions.length,
        question_types: survey.questions.map((question) => question.type),
        is_duplicate: isDuplicate ?? false,
        creation_source: creationSource ?? 'full_editor',
        linked_insight_id: survey.linked_insight_id,
        ...getSurveyConfigurationProperties(survey),
    }
}

export function reportSurveyEdited(survey: Survey): void {
    posthog.capture('survey edited', getSurveyEditedProperties(survey))
}

export function reportSurveyCreated(
    survey: Survey,
    isDuplicate?: boolean,
    creationSource?: SurveyCreationSource
): void {
    posthog.capture('survey created', getSurveyCreatedProperties(survey, isDuplicate, creationSource))
}
