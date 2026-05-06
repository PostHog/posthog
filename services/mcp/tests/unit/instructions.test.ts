import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import {
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
    buildQueryToolsCompact,
    buildToolDomainsBlock,
    buildToolDomainsCompact,
    QueryToolCatalog,
    type QueryToolInfo,
} from '@/lib/instructions'

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
        expect(buildDefinedGroupsBlock(groupTypes)).toBe('Defined group types: organization, instance, business')
    })

    it('should ignore singular/plural names and only use group_type', () => {
        const groupTypes: GroupType[] = [
            { group_type: 'workspace', group_type_index: 0, name_singular: 'Workspace', name_plural: 'Workspaces' },
        ]
        expect(buildDefinedGroupsBlock(groupTypes)).toBe('Defined group types: workspace')
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

describe('buildToolDomainsCompact', () => {
    it('renders domains as a single pipe-separated line', () => {
        const tools = [
            { name: 'experiment-create', category: 'Experiments' },
            { name: 'experiment-get', category: 'Experiments' },
            { name: 'survey-create', category: 'Surveys' },
            { name: 'survey-get', category: 'Surveys' },
            { name: 'execute-sql', category: 'SQL' },
        ]
        expect(buildToolDomainsCompact(tools)).toBe('execute-sql|experiment|survey')
    })

    it('returns an empty string for an empty array', () => {
        expect(buildToolDomainsCompact([])).toBe('')
    })
})

describe('QueryToolCatalog', () => {
    it('filters to query-* tools only', () => {
        const tools: QueryToolInfo[] = [
            { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
            { name: 'dashboard-create', title: 'Create dashboard', systemPromptHint: 'not a query' },
            { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
        ]
        const result = new QueryToolCatalog(tools).toMarkdown()
        expect(result).toContain('`query-trends`')
        expect(result).toContain('`query-funnel`')
        expect(result).not.toContain('dashboard-create')
    })

    it('sorts tools alphabetically', () => {
        const tools: QueryToolInfo[] = [
            { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
            { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
            { name: 'query-lifecycle', title: 'Lifecycle', systemPromptHint: 'user composition' },
        ]
        const result = new QueryToolCatalog(tools).toMarkdown()
        const lines = result.split('\n')
        expect(lines).toEqual([
            '- `query-funnel` — conversion rate',
            '- `query-lifecycle` — user composition',
            '- `query-trends` — time series',
        ])
    })

    it('prefers systemPromptHint over title', () => {
        const tools: QueryToolInfo[] = [
            { name: 'query-trends', title: 'Run a trends query', systemPromptHint: 'time series' },
        ]
        const result = new QueryToolCatalog(tools).toMarkdown()
        expect(result).toBe('- `query-trends` — time series')
    })

    it('falls back to title when systemPromptHint is missing', () => {
        const tools: QueryToolInfo[] = [{ name: 'query-trends', title: 'Run a trends query' }]
        const result = new QueryToolCatalog(tools).toMarkdown()
        expect(result).toBe('- `query-trends` — Run a trends query')
    })

    it('returns empty string for empty input', () => {
        expect(new QueryToolCatalog([]).toMarkdown()).toBe('')
    })

    it('returns empty string when no tools match query-*', () => {
        const tools: QueryToolInfo[] = [{ name: 'dashboard-create', title: 'Create dashboard' }]
        expect(new QueryToolCatalog(tools).toMarkdown()).toBe('')
    })

    it('buildQueryToolsBlock delegates to QueryToolCatalog.toMarkdown', () => {
        const tools: QueryToolInfo[] = [{ name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' }]
        expect(buildQueryToolsBlock(tools)).toBe('- `query-trends` — time series')
    })

    describe('toCompact', () => {
        it('renders names pipe-separated and strips the query- prefix', () => {
            const tools: QueryToolInfo[] = [
                { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
                { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion' },
                { name: 'query-lifecycle', title: 'Lifecycle' },
            ]
            expect(new QueryToolCatalog(tools).toCompact()).toBe('funnel|lifecycle|trends')
        })

        it('ignores non-query tools', () => {
            const tools: QueryToolInfo[] = [
                { name: 'query-trends', title: 'Trends' },
                { name: 'dashboard-create', title: 'Create dashboard' },
            ]
            expect(new QueryToolCatalog(tools).toCompact()).toBe('trends')
        })

        it('returns empty string for empty input', () => {
            expect(new QueryToolCatalog([]).toCompact()).toBe('')
        })

        it('buildQueryToolsCompact delegates to QueryToolCatalog.toCompact', () => {
            const tools: QueryToolInfo[] = [{ name: 'query-trends', title: 'Trends' }]
            expect(buildQueryToolsCompact(tools)).toBe('trends')
        })
    })
})
