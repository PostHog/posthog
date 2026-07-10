import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import {
    buildActiveEnvironmentContextPrompt,
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
    buildToolDomainsBlock,
    buildToolDomainsCompact,
    QueryToolCatalog,
    type QueryToolInfo,
} from '@/lib/instructions'
import type { CachedOrg, CachedProject, CachedUser } from '@/tools/types'

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

    it('keeps a singleton tool whole but collapses siblings to a shared root', () => {
        const tools = [
            { name: 'execute-sql', category: 'SQL' },
            { name: 'external-data-schemas-list', category: 'Data warehouse' },
            { name: 'external-data-sources-list', category: 'Data warehouse' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- execute-sql')
        // external-data-* siblings collapse to their shared prefix, not listed verbatim
        expect(result).toContain('- external-data')
        expect(result).not.toContain('- external-data-schemas-list')
        expect(result).not.toContain('- external-data-sources-list')
    })

    it('splits an oversized family into sub-family roots, one level deep', () => {
        // A flat CRUD family below the size cap stays whole; a large area is
        // broken into searchable sub-roots instead of listing leaf tools verbatim.
        const llma = [
            'llma-personal-spend',
            'llma-prompt-create',
            'llma-prompt-get',
            'llma-skill-archive',
            'llma-skill-file-rename',
            'llma-evaluation-config-set-active-key',
            'llma-evaluation-judge-models',
            'llma-evaluation-run',
        ]
        const tools = [
            ...Array.from({ length: 30 }, (_, i) => ({ name: `llma-filler-${i}`, category: 'AI observability' })),
            ...llma.map((name) => ({ name, category: 'AI observability' })),
        ]
        const result = buildToolDomainsCompact(tools)
        const domains = result.split('|')
        // sub-family roots, never the verbose leaf names
        expect(domains).toContain('llma-prompt')
        expect(domains).toContain('llma-skill')
        expect(domains).toContain('llma-evaluation')
        expect(result).not.toContain('llma-skill-file-rename')
        expect(result).not.toContain('llma-evaluation-config-set-active-key')
    })

    it('collapses all query-* tools into a single "query" domain', () => {
        const tools = [
            { name: 'query-trends', category: 'Query wrappers' },
            { name: 'query-funnel', category: 'Query wrappers' },
            { name: 'experiment-create', category: 'Experiments' },
        ]
        const result = buildToolDomainsBlock(tools)
        expect(result).toContain('- query')
        // never fragmented into per-insight roots
        expect(result).not.toContain('query-trends')
        expect(result).not.toContain('query-funnel')
        expect(result).toContain('- experiment')
    })

    it('omits the "query" domain when no query-* tools are present', () => {
        const result = buildToolDomainsBlock([{ name: 'experiment-create', category: 'Experiments' }])
        expect(result).not.toContain('query')
    })

    it('should collapse plural/singular duplicates', () => {
        const tools = [
            { name: 'evaluation-create', category: 'AI observability' },
            { name: 'evaluations-get', category: 'AI observability' },
            { name: 'evaluation-delete', category: 'AI observability' },
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
})

describe('buildActiveEnvironmentContextPrompt', () => {
    const org = { id: 'org_1', name: 'Acme' } satisfies Partial<CachedOrg> as unknown as CachedOrg
    const project = {
        id: 1,
        name: 'My App',
        timezone: 'America/New_York',
        api_token: 'token_1',
        person_on_events_querying_enabled: false,
    } satisfies Partial<CachedProject> as unknown as CachedProject
    const user = {
        first_name: 'Jane',
        last_name: 'Doe',
        email: 'jane@acme.com',
    } satisfies Partial<CachedUser> as unknown as CachedUser

    it('renders the full project + org line when both are present', () => {
        const result = buildActiveEnvironmentContextPrompt(user, org, project)
        expect(result).toContain(
            'You are currently in project "My App" (id: 1, token: token_1) within organization "Acme" (id: org_1).'
        )
    })

    it('omits the organization clause when org is undefined (scope-gated path)', () => {
        // Project-scoped personal API keys lack `organization:read`, so the org
        // fetch is skipped. The line drops the "within organization …" tail
        // rather than rendering a fabricated "Unknown" placeholder.
        const result = buildActiveEnvironmentContextPrompt(user, undefined, project)
        expect(result).toContain('You are currently in project "My App" (id: 1, token: token_1).')
        expect(result).not.toContain('within organization')
        expect(result).not.toContain('Unknown')
        expect(result).not.toContain('unknown')
    })

    it('keeps the timezone and user lines when org is omitted', () => {
        const result = buildActiveEnvironmentContextPrompt(user, undefined, project)
        expect(result).toContain('Project timezone: America/New_York.')
        expect(result).toContain("The user's name is Jane Doe (jane@acme.com).")
    })

    it('renders a single base URL line (scheme stripped, project segment appended) when a base URL is given', () => {
        const result = buildActiveEnvironmentContextPrompt(user, org, project, 'https://us.posthog.com')
        expect(result).toContain('Base URL: us.posthog.com — add /project/1 for project-scoped paths.')
        // Sits right after the project/org context line.
        const lines = (result ?? '').split('\n')
        expect(lines.indexOf('Base URL: us.posthog.com — add /project/1 for project-scoped paths.')).toBe(
            lines.indexOf(
                'You are currently in project "My App" (id: 1, token: token_1) within organization "Acme" (id: org_1).'
            ) + 1
        )
    })

    it('renders the base URL without a project segment when no project is active', () => {
        const result = buildActiveEnvironmentContextPrompt(user, undefined, undefined, 'https://us.posthog.com')
        expect(result).toContain('Base URL: us.posthog.com.')
        expect(result).not.toContain('/project/')
    })

    it('omits the base URL line when no base URL is given', () => {
        const result = buildActiveEnvironmentContextPrompt(user, org, project)
        expect(result).not.toContain('Base URL:')
    })

    it('returns undefined when no context is available at all', () => {
        expect(buildActiveEnvironmentContextPrompt(undefined, undefined, undefined)).toBeUndefined()
    })

    it('still renders an "Unknown" project when org is present but project is missing', () => {
        // The org branch is unchanged — only the no-org branch was added.
        const result = buildActiveEnvironmentContextPrompt(user, org, undefined)
        expect(result).toContain(
            'You are currently in project "Unknown" (id: unknown, token: unknown) within organization "Acme" (id: org_1).'
        )
    })
})
