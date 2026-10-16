import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/billing'

describe('billing usage filters', () => {
    it.each(['billing-spend-get', 'billing-usage-get'])('%s documents usage types for array inputs', (toolName) => {
        const schema = z.toJSONSchema(GENERATED_TOOLS[toolName]!().schema)
        const usageTypes = schema.properties!.usage_types!

        expect(usageTypes).toHaveProperty('description', expect.stringContaining('survey_responses_count_in_period'))
        expect(usageTypes).not.toHaveProperty('description', expect.stringContaining('JSON-encoded'))
        expect(usageTypes).toMatchObject({
            anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }],
        })
        expect(schema.required ?? []).not.toContain('usage_types')
    })

    it.each(['billing-spend-get', 'billing-usage-get'])('%s accepts null filters', (toolName) => {
        const input = { team_ids: null, usage_types: null, breakdowns: null }
        const result = GENERATED_TOOLS[toolName]!().schema.safeParse(input)

        expect(result.success).toBe(true)
        expect(result.data).toMatchObject(input)
    })
})
