import { describe, expect, it } from 'vitest'

import { SurveysCreateBody, SurveysPartialUpdateBody } from '@/generated/surveys/api'

// Regression guard: survey responses are keyed $survey_response_<question_id>, so the MCP
// survey tools must let callers send back an existing question id on edit. If the `id` field
// is dropped from the question schema, zod silently strips it and every edit regenerates the
// UUID, orphaning historical responses (support ticket 61130).
describe('Survey question id preservation', () => {
    it.each([
        ['survey-create', SurveysCreateBody.shape.questions],
        ['survey-update', SurveysPartialUpdateBody.shape.questions],
    ])('preserves an explicit question id through %s validation', (_label, questionsSchema) => {
        const existingId = '0190a1b2-c3d4-7e8f-9012-3456789abcde'

        const result = questionsSchema.safeParse([
            { type: 'open', question: 'How was your experience?', id: existingId },
        ])

        expect(result.success).toBe(true)
        expect(result.data?.[0]).toMatchObject({ id: existingId })
    })
})
