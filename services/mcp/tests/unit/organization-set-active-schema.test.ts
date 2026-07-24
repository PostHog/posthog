import { describe, expect, it } from 'vitest'

import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'

describe('OrganizationSetActiveSchema', () => {
    it.each([
        ['orgId', { orgId: 'org-123' }, 'org-123'],
        // `organizations-list` / `organization-get` return the org under `id`, and in
        // exec mode agents reconstruct the field name from context — every one of these
        // aliases must normalize to `orgId` or the exec-mode failures come back.
        ['id alias', { id: 'org-456' }, 'org-456'],
        ['organizationId alias', { organizationId: 'org-789' }, 'org-789'],
        ['organization_id alias', { organization_id: 'org-abc' }, 'org-abc'],
        ['org_id alias', { org_id: 'org-def' }, 'org-def'],
        ['orgId takes precedence over id', { orgId: 'org-123', id: 'org-456' }, 'org-123'],
    ])('accepts %s and normalizes to orgId', (_label, input, expected) => {
        const result = OrganizationSetActiveSchema.safeParse(input)
        expect(result.success).toBe(true)
        expect(result.data).toEqual({ orgId: expected })
    })

    it('rejects input with no recognized identifier', () => {
        const result = OrganizationSetActiveSchema.safeParse({})
        expect(result.success).toBe(false)
        expect(result.error?.issues[0]?.message).toContain('orgId')
    })
})
