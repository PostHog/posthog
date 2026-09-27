import { describe, expect, it } from 'vitest'

import { hasScopes } from '@/lib/api'
import { getToolDefinition } from '@/tools/toolDefinitions'

// The catalog filter is all-or-nothing (`hasScopes` requires every declared scope), so a scope
// stricter than AlertViewSet.simulate enforces hides the tool from a read-only scout instead of
// erroring. That viewset needs alert:read and insight:read; alert:write is demanded later, and
// only for the charged AI detector.
const READ_ONLY_SCOUT_SCOPES = ['alert:read', 'insight:read']

describe('alert simulate tool scopes', () => {
    it('stays visible to a read-only scout credential', () => {
        const required = getToolDefinition('alert-simulate').required_scopes ?? []

        expect(hasScopes(READ_ONLY_SCOUT_SCOPES, required)).toBe(true)
    })

    it.each(['alert-create', 'alert-update', 'alert-delete', 'alert-destinations-create', 'alert-destinations-delete'])(
        '%s stays hidden from a read-only scout credential',
        (toolName) => {
            const required = getToolDefinition(toolName).required_scopes ?? []

            expect(hasScopes(READ_ONLY_SCOUT_SCOPES, required)).toBe(false)
        }
    )
})
