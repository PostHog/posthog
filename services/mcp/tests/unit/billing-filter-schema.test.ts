import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/billing'

describe('billing usage filters', () => {
    it.each(['billing-spend-get', 'billing-usage-get'])('%s accepts null filters', (toolName) => {
        const input = { team_ids: null, usage_types: null, breakdowns: null }
        const result = GENERATED_TOOLS[toolName]!().schema.safeParse(input)

        expect(result.success).toBe(true)
        expect(result.data).toMatchObject(input)
    })
})
