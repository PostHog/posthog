import posthog from 'posthog-js'

import { getSurveyIdBasedResponseKey, getSurveyResponseKey } from 'scenes/surveys/utils'

import { SurveyEventName, SurveyEventProperties } from '~/types'

export interface SurveyAnswer {
    questionIndex: number
    questionId: string
    value: string
}

export interface SurveyResponseCapture {
    surveyId: string
    /** The same id on two captures makes them one response in the survey results. */
    submissionId: string
    completed: boolean
    answers: SurveyAnswer[]
    /** Distinguishes responses when several surfaces report to one survey. */
    surface: string
}

/** Records answers to an `api`-type survey, which has no SDK form to capture them. */
export function captureSurveyResponse({
    surveyId,
    submissionId,
    completed,
    answers,
    surface,
}: SurveyResponseCapture): void {
    const responses = Object.fromEntries(
        answers.flatMap(({ questionIndex, questionId, value }) => [
            [getSurveyResponseKey(questionIndex), value],
            [getSurveyIdBasedResponseKey(questionId), value],
        ])
    )
    posthog.capture(SurveyEventName.SENT, {
        [SurveyEventProperties.SURVEY_ID]: surveyId,
        [SurveyEventProperties.SURVEY_SUBMISSION_ID]: submissionId,
        [SurveyEventProperties.SURVEY_COMPLETED]: completed,
        ...responses,
        feedback_surface: surface,
    })
}
