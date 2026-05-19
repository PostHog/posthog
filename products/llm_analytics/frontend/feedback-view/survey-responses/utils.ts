import { getSurveyResponseValue } from 'scenes/surveys/utils'

import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { Survey, SurveyEventProperties, SurveyQuestion } from '~/types'

export interface GroupedResponse {
    submissionId: string
    surveyId: string
    responses: { questionIndex: number; question: SurveyQuestion; value: unknown }[]
    isComplete: boolean
}

export function groupEventsBySubmission(events: LLMTraceEvent[], surveys: Record<string, Survey>): GroupedResponse[] {
    const submissionMap = new Map<string, GroupedResponse>()

    for (const event of events) {
        const props = event.properties || {}
        const surveyId = props[SurveyEventProperties.SURVEY_ID]
        const survey = surveyId ? surveys[surveyId] : null

        if (!survey) {
            continue
        }

        const submissionId = props[SurveyEventProperties.SURVEY_SUBMISSION_ID] || event.id

        if (!submissionMap.has(submissionId)) {
            submissionMap.set(submissionId, {
                submissionId,
                surveyId,
                responses: [],
                isComplete: props[SurveyEventProperties.SURVEY_COMPLETED] === true,
            })
        }

        const submission = submissionMap.get(submissionId)!

        for (let i = 0; i < survey.questions.length; i++) {
            const question = survey.questions[i]
            const value = getSurveyResponseValue(props, i, question.id)

            if (value != null && value !== '') {
                const existing = submission.responses.find((r) => r.questionIndex === i)
                if (!existing) {
                    submission.responses.push({ questionIndex: i, question, value })
                }
            }
        }

        if (props[SurveyEventProperties.SURVEY_COMPLETED] === true) {
            submission.isComplete = true
        }
    }

    return Array.from(submissionMap.values())
}
