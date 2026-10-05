import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/integrations'

// Agents send the integration id as `integrationId`, `integration_id`, or a numeric string.
// Each spelling must resolve to the numeric `id`, or those validation failures come back.
describe('integration-get id input', () => {
    const schema = GENERATED_TOOLS['integration-get']!().schema
    const ALIAS_KEYS = ['integrationId', 'integration_id'] as const

    it.each([
        ['id (numeric)', { id: 4321 }],
        ['id (numeric string)', { id: '4321' }],
        ['integrationId', { integrationId: 4321 }],
        ['integrationId (numeric string)', { integrationId: '4321' }],
        ['integration_id', { integration_id: 4321 }],
        ['id over aliases on conflict', { id: 4321, integrationId: 999 }],
    ])('accepts %s', (_label, input) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toBe(4321)
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
