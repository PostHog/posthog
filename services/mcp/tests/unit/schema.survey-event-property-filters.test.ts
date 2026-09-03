import { describe, expect, it } from 'vitest'

import { SurveysCreateBody, SurveysPartialUpdateBody } from '@/generated/surveys/api'

// Regression guard: an event trigger can filter on the properties of the triggering event. If
// `propertyFilters` is dropped from the event value schema, zod silently strips it and the survey
// starts showing on every event with that name, which widens the targeting without any error.
describe('Survey event trigger property filters', () => {
    it.each([
        ['survey-create', SurveysCreateBody().shape.conditions],
        ['survey-update', SurveysPartialUpdateBody().shape.conditions],
    ])('preserves event property filters through %s validation', (_label, conditionsSchema) => {
        const propertyFilters = {
            plan: { values: ['enterprise'], operator: 'exact' },
            seats: { values: ['10'], operator: 'gte' },
        }

        const result = conditionsSchema.safeParse({
            events: { values: [{ name: 'checkout_completed', propertyFilters }] },
        })

        expect(result.success).toBe(true)
        expect(result.data?.events?.values?.[0]).toMatchObject({ propertyFilters })
    })

    it('rejects an operator the SDKs cannot match on', () => {
        const result = SurveysPartialUpdateBody().shape.conditions.safeParse({
            events: {
                values: [{ name: 'checkout_completed', propertyFilters: { plan: { values: [], operator: 'is_set' } } }],
            },
        })

        expect(result.success).toBe(false)
    })
})
