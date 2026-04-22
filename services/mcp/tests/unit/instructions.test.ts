import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import { buildDefinedGroupsBlock, buildInstructionsV2, buildToolDomainsBlock } from '@/lib/instructions'

const MOCK_TEMPLATE = `{metadata}

### Basic functionality
Some instructions here.

{guidelines}

{tool_domains}

### Examples
Some examples here.

Defined group types: {defined_groups}`

describe('buildDefinedGroupsBlock', () => {
    it('should format group types as a comma-separated list of group_type names', () => {
        const groupTypes: GroupType[] = [
            {
                group_type: 'organization',
                group_type_index: 0,
                name_singular: 'Organization',
                name_plural: 'Organizations',
            },
            { group_type: 'instance', group_type_index: 1, name_singular: 'Instance', name_plural: 'Instances' },
            { group_type: 'business', group_type_index: 2, name_singular: null, name_plural: null },
        ]
        expect(buildDefinedGroupsBlock(groupTypes)).toBe('organization, instance, business')
    })

    it('should ignore singular/plural names and only use group_type', () => {
        const groupTypes: GroupType[] = [
            { group_type: 'workspace', group_type_index: 0, name_singular: 'Workspace', name_plural: 'Workspaces' },
        ]
        expect(buildDefinedGroupsBlock(groupTypes)).toBe('workspace')
    })

    it('should return empty string for undefined', () => {
        expect(buildDefinedGroupsBlock(undefined)).toBe('')
    })

    it('should return empty string for empty array', () => {
        expect(buildDefinedGroupsBlock([])).toBe('')
    })
})

describe('buildToolDomainsBlock', () => {
    it('should extract CRUD domains from tool names grouped by category', () => {
        const tools = [
            { name: 'experiment-create', category: 'Experiments' },
            { name: 'experiment-get', category: 'Experiments' },
            { name: 'experiment-delete', category: 'Experiments' },
            { name: 'survey-create', category: 'Surveys' },
            { name: 'survey-get', category: 'Surveys' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- experiment')
        expect(result).toContain('- survey')
    })

    it('should list standalone tools as-is', () => {
        const tools = [
            { name: 'execute-sql', category: 'SQL' },
            { name: 'read-data-schema', category: 'Data schema' },
            { name: 'read-data-warehouse-schema', category: 'Data schema' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- execute-sql')
        expect(result).toContain('- read-data-schema')
        expect(result).toContain('- read-data-warehouse-schema')
    })

    it('should skip query-* tools', () => {
        const tools = [
            { name: 'query-trends', category: 'Query wrappers' },
            { name: 'query-funnel', category: 'Query wrappers' },
            { name: 'experiment-create', category: 'Experiments' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).not.toContain('query')
        expect(result).toContain('- experiment')
    })

    it('should collapse plural/singular duplicates', () => {
        const tools = [
            { name: 'evaluation-create', category: 'LLM analytics' },
            { name: 'evaluations-get', category: 'LLM analytics' },
            { name: 'evaluation-delete', category: 'LLM analytics' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- evaluation')
        expect(result).not.toContain('- evaluations')
    })

    it('should collapse sub-domains under their parent', () => {
        const tools = [
            { name: 'feature-flag-get-all', category: 'Feature flags' },
            { name: 'create-feature-flag', category: 'Feature flags' },
            { name: 'feature-flags-activity-retrieve', category: 'Feature flags' },
            { name: 'feature-flags-status-retrieve', category: 'Feature flags' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- feature-flag')
        expect(result).not.toContain('- feature-flags-activity')
        expect(result).not.toContain('- feature-flags-status')
    })

    it('should handle prefix-action tools (create-X, delete-X)', () => {
        const tools = [
            { name: 'create-feature-flag', category: 'Feature flags' },
            { name: 'update-feature-flag', category: 'Feature flags' },
            { name: 'delete-feature-flag', category: 'Feature flags' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- feature-flag')
    })

    it('should return empty string for empty array', () => {
        expect(buildToolDomainsBlock([])).toBe('')
    })
})

describe('buildInstructionsV2', () => {
    it('should replace all placeholders', () => {
        const groupTypes: GroupType[] = [
            {
                group_type: 'organization',
                group_type_index: 0,
                name_singular: 'Organization',
                name_plural: 'Organizations',
            },
            { group_type: 'instance', group_type_index: 1, name_singular: null, name_plural: null },
        ]
        const tools = [
            { name: 'dashboard-create', category: 'Dashboards' },
            { name: 'dashboard-get', category: 'Dashboards' },
            { name: 'action-create', category: 'Actions' },
            { name: 'action-get', category: 'Actions' },
        ]
        const result = buildInstructionsV2(MOCK_TEMPLATE, '  some guidelines  ', groupTypes, undefined, tools)
        expect(result).toContain('some guidelines')
        expect(result).toContain('Defined group types: organization, instance')
        expect(result).toContain('- action\n- dashboard')
        expect(result).not.toContain('{guidelines}')
        expect(result).not.toContain('{defined_groups}')
        expect(result).not.toContain('{tool_domains}')
    })

    it('should leave no placeholders when no group types or tools', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined)
        expect(result).not.toContain('{guidelines}')
        expect(result).not.toContain('{defined_groups}')
        expect(result).not.toContain('{tool_domains}')
    })

    it('should trim guidelines whitespace', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, '  padded  ', undefined)
        expect(result).toContain('padded')
        expect(result).not.toContain('  padded  ')
    })

    it('should inject metadata into the template', () => {
        const metadata =
            'You are currently in project "My App" (organization: "Acme Corp").\nThe user\'s name is Jane Doe (jane@acme.com).\nProject timezone: America/New_York.'
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined, metadata)
        expect(result).toContain('You are currently in project "My App" (organization: "Acme Corp").')
        expect(result).toContain("The user's name is Jane Doe (jane@acme.com).")
        expect(result).toContain('Project timezone: America/New_York.')
        expect(result).not.toContain('{metadata}')
    })

    it('should place metadata before the basic functionality section', () => {
        const metadata = 'Project: Test'
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined, metadata)
        const metadataIndex = result.indexOf('Project: Test')
        const basicIndex = result.indexOf('### Basic functionality')
        expect(metadataIndex).toBeLessThan(basicIndex)
    })

    it('should leave no placeholder when metadata is undefined', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined, undefined)
        expect(result).not.toContain('{metadata}')
    })

    it('should trim metadata whitespace', () => {
        const result = buildInstructionsV2(MOCK_TEMPLATE, 'guidelines', undefined, '  padded metadata  ')
        expect(result).toContain('padded metadata')
        expect(result).not.toContain('  padded metadata  ')
    })
})
