import { describe, expect, it } from 'vitest'

import { SurveysCreateBody, SurveysPartialUpdateBody } from '@/generated/surveys/api'

// Regression guard: survey responses are keyed $survey_response_<question_id>, so the MCP
// survey tools must let callers send back an existing question id on edit. If the `id` field
// is dropped from the question schema, zod silently strips it and every edit regenerates the
// UUID, orphaning historical responses (support ticket 61130).
describe('Survey question id preservation', () => {
    it.each([
        ['survey-create', SurveysCreateBody().shape.questions],
        ['survey-update', SurveysPartialUpdateBody().shape.questions],
    ])('preserves an explicit question id through %s validation', (_label, questionsSchema) => {
        const existingId = '0190a1b2-c3d4-7e8f-9012-3456789abcde'

        const result = questionsSchema.safeParse([
            { type: 'open', question: 'How was your experience?', id: existingId },
        ])

        expect(result.success).toBe(true)
        expect(result.data?.[0]).toMatchObject({ id: existingId })
    })

    // A wording edit resends the full questions array. Zod strips any field the schema omits,
    // and the survey then saves without that setting.
    it.each([
        ['survey-create', SurveysCreateBody().shape.questions],
        ['survey-update', SurveysPartialUpdateBody().shape.questions],
    ])('keeps every question setting through %s validation', (_label, questionsSchema) => {
        const questions = [
            {
                type: 'rating',
                question: 'How likely are you to recommend us?',
                scale: 10,
                isNpsQuestion: false,
                branching: { type: 'response_based', responseValues: { promoters: 'end' } },
                translations: { es: { question: '¿Nos recomendarías?', lowerBoundLabel: 'Nada probable' } },
            },
            {
                type: 'open',
                question: 'What should we improve?',
                validation: [{ type: 'min_length', value: 20 }],
                branching: { type: 'specific_question', index: 0 },
                translations: { fr: { question: 'Que devrions-nous améliorer ?' } },
            },
            {
                type: 'link',
                question: 'Read the release notes',
                link: 'https://example.com/notes',
                branching: { type: 'end' },
                translations: { de: { link: 'https://example.com/de/notes' } },
            },
            {
                type: 'open',
                question: 'Anything else?',
                validation: null,
            },
        ]

        const result = questionsSchema.safeParse(questions)

        expect(result.success).toBe(true)
        expect(result.data).toEqual(questions)
    })

    it.each([
        ['survey-create', SurveysCreateBody().shape.questions],
        ['survey-update', SurveysPartialUpdateBody().shape.questions],
    ])('rejects null question translations through %s validation', (_label, questionsSchema) => {
        const result = questionsSchema.safeParse([
            { type: 'open', question: 'How was your experience?', translations: null },
        ])

        expect(result.success).toBe(false)
    })
})
