import { describe, expect, it } from 'vitest'

import { SurveysCreateBody, SurveysPartialUpdateBody } from '@/generated/surveys/api'

// Regression guard: zod strips any condition key the schema does not declare, and an update replaces
// the whole conditions object. A key that goes missing here silently widens the targeting of a live
// survey: an event trigger loses its property filters, a pending survey loses its cancel events, and
// the backend clears the survey's linked actions.
describe('Survey display conditions schema', () => {
    const conditions = {
        events: {
            values: [
                {
                    name: 'checkout_completed',
                    propertyFilters: {
                        plan: { values: ['enterprise'], operator: 'exact' },
                        seats: { values: ['10'], operator: 'gt' },
                    },
                },
            ],
        },
        cancelEvents: { values: [{ name: 'checkout_abandoned' }] },
        actions: { values: [{ id: 42, name: 'Clicked buy' }] },
    }

    it.each([
        ['survey-create', SurveysCreateBody().shape.conditions],
        ['survey-update', SurveysPartialUpdateBody().shape.conditions],
    ])('preserves event filters, cancel events and actions through %s validation', (_label, conditionsSchema) => {
        const result = conditionsSchema.safeParse(conditions)

        expect(result.success).toBe(true)
        expect(result.data).toMatchObject(conditions)
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
