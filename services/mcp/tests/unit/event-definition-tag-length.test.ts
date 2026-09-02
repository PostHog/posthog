import { describe, expect, it } from 'vitest'

import { EventDefinitionCreateSchema } from '@/schema/tool-inputs'

describe('EventDefinitionCreateSchema tag validation', () => {
    it('rejects tags that exceed the database limit after normalization', () => {
        const expandingTag = 'İ'.repeat(200)

        expect(expandingTag.length).toBeLessThanOrEqual(255)
        expect(expandingTag.trim().toLowerCase().length).toBeGreaterThan(255)
        expect(
            EventDefinitionCreateSchema.safeParse({
                eventName: 'test_event',
                data: { tags: [expandingTag] },
            }).success
        ).toBe(false)
    })
})
