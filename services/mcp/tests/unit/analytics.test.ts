import { describe, expect, it } from 'vitest'

import { buildMCPAnalyticsGroups, buildMCPContextProperties, type MCPAnalyticsContext } from '@/lib/analytics'

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

describe('buildMCPContextProperties', () => {
    it.each<[string, MCPAnalyticsContext, { prefix?: string } | undefined, Record<string, string>]>([
        [
            'full context → snake_case properties',
            {
                organizationId: 'org-1',
                projectId: '123',
                projectUuid: 'project-uuid-123',
                projectName: 'My Project',
            },
            undefined,
            {
                organization_id: 'org-1',
                project_id: '123',
                project_uuid: 'project-uuid-123',
                project_name: 'My Project',
            },
        ],
        [
            'prefix applies to every key (used for previous_* on context-switch events)',
            { organizationId: 'org-1', projectUuid: 'project-uuid-123' },
            { prefix: 'previous_' },
            { previous_organization_id: 'org-1', previous_project_uuid: 'project-uuid-123' },
        ],
        ['empty context yields empty object', {}, undefined, {}],
        [
            'partial context omits absent keys rather than emitting undefined',
            { organizationId: 'org-1' },
            undefined,
            { organization_id: 'org-1' },
        ],
    ])('%s', (_, input, options, expected) => {
        expect(buildMCPContextProperties(input, options)).toEqual(expected)
    })
})
