import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/integrations'

// Production traces show agents sending the right integration under a different key
// spelling, or as a stringified id. Both were rejected before the param overrides.
describe('integration-get id input', () => {
    const schema = GENERATED_TOOLS['integration-get']!().schema
    const ALIAS_KEYS = ['integrationId', 'integration_id'] as const

    it.each([
        ['id (numeric)', { id: 262363 }],
        ['id (stringified)', { id: '262363' }],
        ['integrationId', { integrationId: 262363 }],
        ['integrationId (stringified)', { integrationId: '262363' }],
        ['integration_id', { integration_id: 262363 }],
        ['id over aliases on conflict', { id: 262363, integrationId: 999 }],
    ])('accepts %s', (_label, input) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toBe(262363)
        for (const alias of ALIAS_KEYS) {
            expect(data).not.toHaveProperty(alias)
        }
    })

    it.each([
        ['no identifier', {}],
        ['a non-numeric id', { id: 'slack' }],
        ['a non-numeric alias', { integrationId: 'slack' }],
    ])('still rejects %s', (_label, input) => {
        expect(schema.safeParse(input).success).toBe(false)
    })
})
