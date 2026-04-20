import { describe, expect, it } from 'vitest'

import { clientSupportsListChanged } from '@/lib/clientCapabilities'
import { SessionManager } from '@/lib/SessionManager'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import { ENABLED_TOOLSETS_KEY, toolsetsHandler } from '@/tools/toolsets/manage'
import {
    BOOTSTRAP_TOOL_NAMES,
    COMPOSITE_TOOLSETS,
    expandToolsetToFeatures,
    getAllToolsets,
    getToolsetById,
    isBootstrapTool,
    isValidToolsetId,
    resolveEnabledFeatures,
} from '@/tools/toolsets/taxonomy'
import type { Context } from '@/tools/types'

function createMockContext(scopes: string[] = ['*'], initialCache: Record<string, any> = {}): Context {
    const store: Record<string, any> = { ...initialCache }
    const cache: any = {
        get: async (key: string) => store[key],
        set: async (key: string, value: any) => {
            store[key] = value
        },
        delete: async (key: string) => {
            delete store[key]
        },
        clear: async () => {
            for (const k of Object.keys(store)) {
                delete store[k]
            }
        },
    }
    return {
        api: {} as any,
        cache,
        env: {
            INKEEP_API_KEY: undefined,
            POSTHOG_API_BASE_URL: undefined,
            MCP_APPS_BASE_URL: undefined,
            POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
            POSTHOG_UI_APPS_TOKEN: undefined,
            POSTHOG_ANALYTICS_API_KEY: undefined,
            POSTHOG_ANALYTICS_HOST: undefined,
        },
        stateManager: {
            getApiKey: async () => ({ scopes }),
            getAiConsentGiven: async () => true,
        } as any,
        sessionManager: new SessionManager(cache),
    }
}

describe('Taxonomy — base toolsets auto-derived from tool definitions', () => {
    it('returns at least one base toolset per product area present in the catalog', () => {
        const all = getAllToolsets()
        const base = all.filter((ts) => ts.isBase)
        // Sanity: we expect base toolsets for core product surfaces.
        const baseIds = new Set(base.map((ts) => ts.id))
        for (const expected of ['flags', 'experiments', 'surveys', 'insights', 'dashboards']) {
            expect(baseIds, `missing base toolset for '${expected}'`).toContain(expected)
        }
    })

    it('excludes bootstrap/internal features (docs, search, debug, skills, meta)', () => {
        const ids = new Set(getAllToolsets().map((ts) => ts.id))
        for (const excluded of ['docs', 'search', 'debug', 'skills', 'meta']) {
            expect(ids, `excluded feature '${excluded}' leaked into toolsets`).not.toContain(excluded)
        }
    })

    it('every non-excluded feature in the catalog appears as a base toolset (no gaps)', () => {
        const defs = getToolDefinitions()
        const excluded = new Set(['docs', 'search', 'debug', 'skills', 'meta'])
        const catalogFeatures = new Set(
            Object.values(defs)
                .map((d) => d.feature)
                .filter((f) => f && !excluded.has(f))
        )
        const baseIds = new Set(
            getAllToolsets()
                .filter((ts) => ts.isBase)
                .map((ts) => ts.id)
        )
        const missing = [...catalogFeatures].filter((f) => !baseIds.has(f))
        expect(missing, `features without a base toolset: ${missing.join(', ')}`).toEqual([])
    })

    it('base toolset titles use the tool-definition category (human-readable)', () => {
        const flagsToolset = getToolsetById('flags')
        expect(flagsToolset?.title).toBe('Feature flags')
        const replayToolset = getToolsetById('replay')
        expect(replayToolset?.title).toBe('Session replays')
    })
})

describe('Taxonomy — composites', () => {
    it('every composite references real base features', () => {
        const baseIds = new Set(
            getAllToolsets()
                .filter((ts) => ts.isBase)
                .map((ts) => ts.id)
        )
        for (const [compositeId, { features }] of Object.entries(COMPOSITE_TOOLSETS)) {
            for (const feature of features) {
                expect(baseIds, `composite '${compositeId}' references missing feature '${feature}'`).toContain(feature)
            }
        }
    })

    it('expanding a composite returns its feature list', () => {
        const analyticsFeatures = expandToolsetToFeatures('analytics')
        expect(analyticsFeatures).toContain('insights')
        expect(analyticsFeatures).toContain('events')
        expect(analyticsFeatures).toContain('cohorts')
    })

    it('expanding a base toolset returns just its own feature id', () => {
        expect(expandToolsetToFeatures('flags')).toEqual(['flags'])
    })

    it('expanding an unknown id returns []', () => {
        expect(expandToolsetToFeatures('not-a-real-toolset')).toEqual([])
    })
})

describe('Taxonomy — resolveEnabledFeatures', () => {
    it('flattens a mix of composites and base ids into the union of features', () => {
        const features = resolveEnabledFeatures(['analytics', 'flags'])
        expect(features.has('insights')).toBe(true)
        expect(features.has('events')).toBe(true)
        expect(features.has('flags')).toBe(true)
    })

    it('ignores unknown ids silently', () => {
        const features = resolveEnabledFeatures(['flags', 'not-real'])
        expect(features.has('flags')).toBe(true)
        expect(features.size).toBe(1)
    })
})

describe('toolsets meta-tool', () => {
    it('list returns composites + base, all disabled initially', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'list' })) as any
        expect(Array.isArray(body.composites)).toBe(true)
        expect(Array.isArray(body.base)).toBe(true)
        expect(body.enabled).toEqual([])
        expect(body.composites.find((c: any) => c.id === 'analytics').enabled).toBe(false)
        expect(body.base.find((b: any) => b.id === 'flags').enabled).toBe(false)
    })

    it('enable on a base toolset persists the id', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'flags' })) as any
        expect(body.enabled).toBe('flags')
        expect(body.enabledNow).toEqual(['flags'])
        expect(body.expandedFeatures).toEqual(['flags'])
        expect(await context.cache.get(ENABLED_TOOLSETS_KEY as any)).toEqual(['flags'])
    })

    it('enable on a composite expands to its features', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'analytics' })) as any
        expect(body.enabled).toBe('analytics')
        expect(body.enabledNow).toEqual(['analytics'])
        expect(body.expandedFeatures).toContain('insights')
        expect(body.expandedFeatures).toContain('events')
    })

    it('enable is idempotent', async () => {
        const context = createMockContext()
        await toolsetsHandler(context, { action: 'enable', name: 'flags' })
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'flags' })) as any
        expect(body.enabledNow).toEqual(['flags'])
    })

    it('describe on a base toolset lists the tools', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'describe', name: 'flags' })) as any
        expect(body.id).toBe('flags')
        expect(body.composite).toBe(false)
        const names = body.tools.map((t: any) => t.name)
        expect(names).toContain('feature-flag-get-all')
    })

    it('describe on a composite shows its bundled features + tools from all of them', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'describe', name: 'analytics' })) as any
        expect(body.id).toBe('analytics')
        expect(body.composite).toBe(true)
        expect(body.bundles).toContain('insights')
        const names = body.tools.map((t: any) => t.name)
        // Analytics includes insights + events + cohorts + actions + persons + product_analytics.
        expect(names.some((n: string) => n.includes('insight'))).toBe(true)
        expect(names.some((n: string) => n.includes('cohort'))).toBe(true)
    })

    it('disable removes the id', async () => {
        const context = createMockContext()
        await toolsetsHandler(context, { action: 'enable', name: 'flags' })
        await toolsetsHandler(context, { action: 'enable', name: 'experiments' })
        const body = (await toolsetsHandler(context, { action: 'disable', name: 'flags' })) as any
        expect(body.disabled).toBe('flags')
        expect(body.enabledNow).toEqual(['experiments'])
    })

    it('rejects unknown toolset ids', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'does-not-exist' })) as any
        expect(body.error).toMatch(/Unknown toolset/)
    })

    it('prompts for name when action needs one', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable' } as any)) as any
        expect(body.error).toMatch(/requires a 'name'/)
    })
})

describe('isValidToolsetId / isBootstrapTool', () => {
    it('isValidToolsetId accepts both base and composite ids', () => {
        expect(isValidToolsetId('flags')).toBe(true)
        expect(isValidToolsetId('analytics')).toBe(true)
        expect(isValidToolsetId('definitely-not-real')).toBe(false)
    })

    it('isBootstrapTool recognizes bootstrap tools', () => {
        expect(isBootstrapTool('query-run')).toBe(true)
        expect(isBootstrapTool('docs-search')).toBe(true)
        expect(isBootstrapTool('toolsets')).toBe(true)
        expect(isBootstrapTool('entity-search')).toBe(true)
        expect(isBootstrapTool('feature-flag-get-all')).toBe(false)
    })

    it('BOOTSTRAP_TOOL_NAMES is the declared source of truth', () => {
        expect(BOOTSTRAP_TOOL_NAMES.length).toBe(4)
    })
})

describe('Bootstrap immunity', () => {
    it('query-run has feature "insights" — used to catch the regression where disabling the "analytics" composite (which includes "insights") would disable query-run', () => {
        const defs = getToolDefinitions()
        // Reality check: query-run is classified under the insights feature in the catalog,
        // and the analytics composite includes insights. So any toolset operation on analytics
        // will attempt to flip query-run too — the mcp.ts loop must exempt bootstrap tools.
        expect(defs['query-run']?.feature).toBe('insights')
        expect(expandToolsetToFeatures('analytics')).toContain('insights')
        expect(isBootstrapTool('query-run')).toBe(true)
    })
})

describe('Client capability detection', () => {
    it('treats unknown clients as supporting list_changed', () => {
        expect(clientSupportsListChanged(undefined)).toBe(true)
        expect(clientSupportsListChanged('')).toBe(true)
        expect(clientSupportsListChanged('claude-code')).toBe(true)
        expect(clientSupportsListChanged('claude-ai')).toBe(true)
    })

    it('flags known-unsupported clients', () => {
        expect(clientSupportsListChanged('Cursor')).toBe(false)
        expect(clientSupportsListChanged('cursor-vscode')).toBe(false)
        expect(clientSupportsListChanged('Windsurf')).toBe(false)
        expect(clientSupportsListChanged('codeium')).toBe(false)
    })
})
