import { describe, expect, it } from 'vitest'

import { buildMCPAnalyticsGroups, type MCPAnalyticsContext } from '@/lib/analytics'

describe('buildMCPAnalyticsGroups', () => {
    it.each<[string, MCPAnalyticsContext, Record<string, string>]>([
        [
            'full context uses UUID as the project group key',
            { organizationId: 'org-1', projectId: '123', projectUuid: 'project-uuid-123' },
            { organization: 'org-1', project: 'project-uuid-123' },
        ],
        ['organization only', { organizationId: 'org-1' }, { organization: 'org-1' }],
        ['project UUID only', { projectUuid: 'project-uuid-123' }, { project: 'project-uuid-123' }],
        ['ignores projectId when projectUuid is absent', { projectId: '123' }, {}],
        ['empty context', {}, {}],
    ])('%s', (_, input, expected) => {
        expect(buildMCPAnalyticsGroups(input)).toEqual(expected)
    })
})
