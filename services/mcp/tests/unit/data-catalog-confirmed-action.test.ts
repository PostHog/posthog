import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/data_catalog'

describe('data catalog confirmed actions', () => {
    it('accepts only confirmation fields when executing a signed rejection', () => {
        const executeSchema = GENERATED_TOOLS['data-catalog-relationship-reject-execute']!().schema
        const confirmation = {
            confirmation_hash: 'signed-token',
            confirmation: 'confirm',
        }

        expect(executeSchema.safeParse(confirmation).success).toBe(true)
        expect(
            executeSchema.safeParse({
                ...confirmation,
                id: 'proposal-id',
                rejection_reason: 'duplicate relationship',
            }).success
        ).toBe(false)
    })
})
