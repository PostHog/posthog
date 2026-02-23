import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { Survey, SurveyQuestionType } from '~/types'

import { groupEventsBySubmission } from './utils'

const SURVEY_RATING_SCALE_THUMB_2_POINT = 2

const thumbQuestion = {
    id: 'q1',
    type: SurveyQuestionType.Rating,
    display: 'emoji',
    scale: SURVEY_RATING_SCALE_THUMB_2_POINT,
    question: 'Was this helpful?',
}

const openTextQuestion = {
    id: 'q2',
    type: SurveyQuestionType.Open,
    question: 'Any feedback?',
}

const makeSurvey = (questions: any[]): Survey =>
    ({
        id: 'survey-1',
        name: 'Test survey',
        questions,
    }) as unknown as Survey

const makeEvent = (overrides: Partial<LLMTraceEvent> & { properties: Record<string, any> }): LLMTraceEvent =>
    ({
        id: 'evt-1',
        event: 'survey sent',
        createdAt: '2026-02-23T00:00:00Z',
        ...overrides,
    }) as LLMTraceEvent

describe('groupEventsBySubmission', () => {
    it.each([
        ['numeric 1', 1],
        ['string "1"', '1'],
    ])('extracts thumb response stored as %s', (_label, responseValue) => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion]) }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_completed: true,
                    $survey_response_q1: responseValue,
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].responses).toHaveLength(1)
        expect(result[0].responses[0].value).toBe(responseValue)
        expect(result[0].isComplete).toBe(true)
    })

    it('extracts response value 0 (falsy but valid)', () => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion]) }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_completed: true,
                    $survey_response_q1: 0,
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].responses).toHaveLength(1)
        expect(result[0].responses[0].value).toBe(0)
    })

    it('returns empty responses when survey question IDs do not match event properties', () => {
        const surveyWithNewId = makeSurvey([{ ...thumbQuestion, id: 'new-id' }])
        const surveys = { 'survey-1': surveyWithNewId }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_completed: true,
                    $survey_response_q1: 1, // old id-based key, won't match 'new-id'
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].responses).toHaveLength(0)
    })

    it('falls back to index-based key when id-based key is missing', () => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion]) }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_completed: true,
                    $survey_response: '1', // index-based key (question index 0)
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].responses).toHaveLength(1)
        expect(result[0].responses[0].value).toBe('1')
    })

    it('handles multi-question surveys', () => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion, openTextQuestion]) }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_completed: true,
                    $survey_response_q1: 1,
                    $survey_response_q2: 'Great product!',
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].responses).toHaveLength(2)
        expect(result[0].responses[0].value).toBe(1)
        expect(result[0].responses[1].value).toBe('Great product!')
    })

    it('skips events whose survey_id is not in the surveys map', () => {
        const surveys = {} as Record<string, Survey>
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'unknown-survey',
                    $survey_response_q1: 1,
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(0)
    })

    it('uses event id as submission id when $survey_submission_id is missing', () => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion]) }
        const events = [
            makeEvent({
                id: 'fallback-id',
                properties: {
                    $survey_id: 'survey-1',
                    $survey_completed: true,
                    $survey_response_q1: 1,
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].submissionId).toBe('fallback-id')
    })

    it('marks incomplete submissions', () => {
        const surveys = { 'survey-1': makeSurvey([thumbQuestion]) }
        const events = [
            makeEvent({
                properties: {
                    $survey_id: 'survey-1',
                    $survey_submission_id: 'sub-1',
                    $survey_response_q1: 1,
                    // $survey_completed is absent
                },
            }),
        ]

        const result = groupEventsBySubmission(events, surveys)
        expect(result).toHaveLength(1)
        expect(result[0].isComplete).toBe(false)
    })
})
