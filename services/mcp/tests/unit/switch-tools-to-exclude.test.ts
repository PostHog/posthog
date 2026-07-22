import { describe, expect, it } from 'vitest'

import { switchToolsToExclude } from '@/hono/request-state-resolver'

describe('switchToolsToExclude', () => {
    const cases = [
        {
            description: 'excludes nothing when nothing is pinned',
            pinned: {},
            expected: [],
        },
        {
            description: 'excludes switch-organization when an organization is pinned',
            pinned: { organizationId: 'org-1' },
            expected: ['switch-organization'],
        },
        {
            // The regression guard: a pinned project must NOT drop the switch tools,
            // or the documented cross-org flow (organizations-get → switch-organization
            // → switch-project) becomes impossible from an active project.
            description: 'excludes nothing when only a project is pinned',
            pinned: { projectId: '2' } as { organizationId?: string; projectId?: string },
            expected: [],
        },
        {
            description: 'keeps project switching available when both are pinned',
            pinned: { organizationId: 'org-1', projectId: '2' },
            expected: ['switch-organization'],
        },
    ]

    it.each(cases)('$description', ({ pinned, expected }) => {
        expect(switchToolsToExclude(pinned)).toEqual(expected)
    })
})
