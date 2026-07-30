import { describe, expect, it } from 'vitest'

import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'

describe('OrganizationSetActiveSchema', () => {
    it.each([
        ['orgId', { orgId: 'org-123' }, 'org-123'],
        // `organizations-list` / `organization-get` return the org under `id`; agents
        // reach for it here too, so it must normalize to `orgId`.
        ['id alias', { id: 'org-456' }, 'org-456'],
        ['orgId takes precedence over id', { orgId: 'org-123', id: 'org-456' }, 'org-123'],
    ])('accepts %s and normalizes to orgId', (_label, input, expected) => {
        const result = OrganizationSetActiveSchema.safeParse(input)
        expect(result.success).toBe(true)
        expect(result.data).toEqual({ orgId: expected })
    })

    it('rejects input with neither orgId nor id', () => {
        const result = OrganizationSetActiveSchema.safeParse({})
        expect(result.success).toBe(false)
        expect(result.error?.issues[0]?.message).toContain('orgId')
    })
})
