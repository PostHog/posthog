import { describe, expect, it } from 'vitest'

import { clientSupportsListChanged } from '@/lib/clientCapabilities'
import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import { getToolsForFeatures } from '@/tools/toolDefinitions'
import { ENABLED_TOOLSETS_KEY, toolsetsHandler } from '@/tools/toolsets/manage'
import { BOOTSTRAP_TOOL_NAMES, TOOLSETS } from '@/tools/toolsets/taxonomy'
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

describe('Progressive disclosure — tool-name filtering', () => {
    it('progressive mode with empty enabledToolsets[] exposes only bootstrap tools', () => {
        // Note: `progressive: true` alone doesn't filter — you have to pass `enabledToolsets: []`
        // to opt into bootstrap-only. This lets mcp.ts register the full catalog at init and
        // dynamically `.enable()` tools without needing to re-init the session.
        const names = getToolsForFeatures({ progressive: true, enabledToolsets: [] })
        const set = new Set(names)
        for (const bt of BOOTSTRAP_TOOL_NAMES) {
            expect(set.has(bt), `bootstrap tool missing: ${bt}`).toBe(true)
        }
        expect(set.has('feature-flag-get-all')).toBe(false)
        expect(set.has('experiment-get-all')).toBe(false)
    })

    it('progressive mode with enabledToolsets=undefined returns the full catalog (for register-all init path)', () => {
        const names = getToolsForFeatures({ progressive: true })
        expect(names).toContain('feature-flag-get-all')
        expect(names).toContain('experiment-get-all')
    })

    it('progressive mode + enabledToolsets=[flags] surfaces flag tools only', () => {
        const names = getToolsForFeatures({
            progressive: true,
            enabledToolsets: ['flags'],
        })
        expect(names).toContain('feature-flag-get-all')
        expect(names).toContain('create-feature-flag')
        expect(names).not.toContain('dashboard-create')
    })

    it('progressive mode + enabledToolsets=[flags,experiments] surfaces both', () => {
        const names = getToolsForFeatures({
            progressive: true,
            enabledToolsets: ['flags', 'experiments'],
        })
        expect(names).toContain('feature-flag-get-all')
        expect(names).toContain('experiment-get-all')
        expect(names).not.toContain('dashboard-create')
    })

    it('unknown toolset ids in enabledToolsets are ignored gracefully', () => {
        const names = getToolsForFeatures({
            progressive: true,
            enabledToolsets: ['analytics', 'not-a-real-toolset'],
        })
        expect(names).toContain('query-run')
    })

    it('default mode (no progressive) omits the toolsets meta-tool from the tool surface', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context, {})
        const names = tools.map((t) => t.name)
        expect(names).not.toContain('toolsets')
        // The catalog itself (getToolsForFeatures) does include 'toolsets' — the exclusion
        // is applied in getToolsFromContext.
    })
})

describe('Progressive disclosure — toolsets meta-tool', () => {
    it("list returns all toolsets with enabled=false when nothing's activated", async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'list' })) as any
        expect(body.toolsets).toHaveLength(TOOLSETS.length)
        expect(body.enabled).toEqual([])
        for (const ts of body.toolsets) {
            expect(ts.enabled).toBe(false)
        }
    })

    it('enable persists the toolset into the cache', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'flags' })) as any
        expect(body.enabled).toBe('flags')
        expect(body.enabledNow).toEqual(['flags'])
        expect(await context.cache.get(ENABLED_TOOLSETS_KEY as any)).toEqual(['flags'])
    })

    it('enable is idempotent', async () => {
        const context = createMockContext()
        await toolsetsHandler(context, { action: 'enable', name: 'flags' })
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'flags' })) as any
        expect(body.enabledNow).toEqual(['flags'])
    })

    it('disable removes the toolset', async () => {
        const context = createMockContext()
        await toolsetsHandler(context, { action: 'enable', name: 'flags' })
        await toolsetsHandler(context, { action: 'enable', name: 'experiments' })
        const body = (await toolsetsHandler(context, { action: 'disable', name: 'flags' })) as any
        expect(body.disabled).toBe('flags')
        expect(body.enabledNow).toEqual(['experiments'])
    })

    it('describe returns tools inside the toolset', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'describe', name: 'flags' })) as any
        expect(body.id).toBe('flags')
        const names = body.tools.map((t: any) => t.name)
        expect(names).toContain('feature-flag-get-all')
    })

    it('rejects unknown toolset ids', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable', name: 'does-not-exist' })) as any
        expect(body.error).toMatch(/Unknown toolset/)
    })

    it('prompts for name when needed', async () => {
        const context = createMockContext()
        const body = (await toolsetsHandler(context, { action: 'enable' } as any)) as any
        expect(body.error).toMatch(/requires a 'name'/)
    })

    it('enabling a toolset then filtering via getToolsForFeatures surfaces its tools', async () => {
        const context = createMockContext()
        await toolsetsHandler(context, { action: 'enable', name: 'flags' })
        const enabled = ((await context.cache.get('enabledToolsets' as any)) ?? []) as string[]
        expect(enabled).toEqual(['flags'])
        // Simulate the mcp.ts filter: progressive + explicitly-passed enabled ids
        const names = getToolsForFeatures({ progressive: true, enabledToolsets: enabled })
        expect(names).toContain('feature-flag-get-all')
        expect(names).toContain('toolsets')
    })
})

describe('Client capability detection', () => {
    it('assumes list_changed supported when client name is missing', () => {
        expect(clientSupportsListChanged(undefined)).toBe(true)
        expect(clientSupportsListChanged('')).toBe(true)
    })

    it('assumes supported for uncataloged clients', () => {
        expect(clientSupportsListChanged('claude-ai')).toBe(true)
        expect(clientSupportsListChanged('claude-code')).toBe(true)
        expect(clientSupportsListChanged('some-new-client')).toBe(true)
    })

    it('flags known-unsupported clients', () => {
        expect(clientSupportsListChanged('Cursor')).toBe(false)
        expect(clientSupportsListChanged('cursor-vscode')).toBe(false)
        expect(clientSupportsListChanged('Windsurf')).toBe(false)
    })
})

describe('Toolset taxonomy', () => {
    it('every tool with a feature either lives in a toolset or is intentionally excluded', async () => {
        const { getToolDefinitions } = await import('@/tools/toolDefinitions')
        const { toolsetIdForFeature } = await import('@/tools/toolsets/taxonomy')
        const defs = getToolDefinitions()
        const allowedUngrouped = new Set(['docs', 'search', 'debug', 'skills', 'meta'])

        const ungrouped: string[] = []
        for (const [name, def] of Object.entries(defs)) {
            if (allowedUngrouped.has(def.feature)) {
                continue
            }
            if (!toolsetIdForFeature(def.feature)) {
                ungrouped.push(`${name} (feature=${def.feature})`)
            }
        }
        expect(ungrouped, `tools missing from toolsets: ${ungrouped.join(', ')}`).toEqual([])
    })

    it('bootstrap tool names are declared', () => {
        expect(BOOTSTRAP_TOOL_NAMES).toContain('query-run')
        expect(BOOTSTRAP_TOOL_NAMES).toContain('toolsets')
        expect(BOOTSTRAP_TOOL_NAMES).toContain('docs-search')
    })
})
