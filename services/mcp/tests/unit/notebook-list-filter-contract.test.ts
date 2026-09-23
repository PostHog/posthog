import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/notebooks'

// A filter the list view does not declare to drf-spectacular never reaches the generated schema, so an
// agent has no way to send it however well the tool description documents it.
describe('notebooks-list filter contract', () => {
    const schema = GENERATED_TOOLS['notebooks-list']!().schema

    const FILTERS = {
        search: 'quarterly review',
        contains: 'recording:true',
        created_by: '00000000-0000-0000-0000-000000000001',
        last_modified_by: '00000000-0000-0000-0000-000000000002',
        date_from: '2026-01-01T00:00:00Z',
        date_to: '2026-02-01T00:00:00Z',
        user: 'true',
    }

    it.each(Object.entries(FILTERS))('accepts the %s filter', (param, value) => {
        const result = schema.safeParse({ [param]: value })

        expect(result.success).toBe(true)
        expect((result.data as Record<string, unknown>)[param]).toBe(value)
    })
})
