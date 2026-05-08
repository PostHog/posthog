import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/feature_flags'

describe('feature-flags-test-evaluation-create schema', () => {
    const tool = GENERATED_TOOLS['feature-flags-test-evaluation-create']!()

    it('rejects when neither distinct_id nor person_id is provided', () => {
        const result = tool.schema.safeParse({ id: 1 })
        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.error.issues[0]?.message).toMatch(/distinct_id or person_id/i)
        }
    })

    it('rejects when both distinct_id and person_id are provided', () => {
        const result = tool.schema.safeParse({ id: 1, distinct_id: 'a', person_id: 'b' })
        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.error.issues[0]?.message).toMatch(/mutually exclusive|both/i)
        }
    })

    it('accepts with only distinct_id', () => {
        const result = tool.schema.safeParse({ id: 1, distinct_id: 'a' })
        expect(result.success).toBe(true)
    })

    it('accepts with only person_id', () => {
        const result = tool.schema.safeParse({ id: 1, person_id: 'b' })
        expect(result.success).toBe(true)
    })

    it('accepts a string id and casts it to a number', () => {
        const result = tool.schema.safeParse({ id: '42', distinct_id: 'a' })
        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.id).toBe(42)
        }
    })
})
