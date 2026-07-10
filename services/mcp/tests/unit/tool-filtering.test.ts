import { describe, expect, it } from 'vitest'

import { OAUTH_HIDDEN_SCOPES, OAUTH_SCOPES_SUPPORTED } from '@/lib/constants'
import type { EvaluatedFlags } from '@/lib/posthog/flags'
import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import {
    getAdvertisedOAuthScopes,
    getToolDefinitions,
    getRequiredFeatureFlags,
    getToolsForFeatures,
    type ToolDefinition,
    toolPassesEntitlementGate,
    toolPassesFlagGate,
} from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

/**
 * Returns every tool name that opts in to `always_available: true`.
 * Tests use this to assert that filtered results never drop these tools,
 * without hard-coding the exact set (which grows as utility tools are added).
 */
const collectAlwaysAvailableToolNames = (): string[] =>
    Object.entries(getToolDefinitions())
        .filter(([_, def]: [string, ToolDefinition]) => def.always_available === true)
        .map(([name]) => name)

describe('Tool Filtering - Features', () => {
    const featureTests = [
        {
            features: undefined,
            description: 'all tools when no features specified',
            expectedTools: [
                'feature-flag-get-definition',
                'dashboard-create',
                'insights-list',
                'organizations-list',
                'organization-get',
            ],
        },
        {
            features: [],
            description: 'all tools when empty array passed',
            expectedTools: ['feature-flag-get-definition', 'dashboard-create'],
        },
        {
            features: ['flags'],
            description: 'flag tools only',
            expectedTools: [
                'feature-flag-get-definition',
                'feature-flag-get-all',
                'create-feature-flag',
                'update-feature-flag',
                'delete-feature-flag',
            ],
        },
        {
            features: ['dashboards', 'product_analytics'],
            description: 'dashboard and insight tools',
            expectedTools: ['dashboard-create', 'dashboards-get-all', 'insights-list', 'insight-create'],
        },
        {
            features: ['workspace'],
            description: 'workspace tools',
            expectedTools: ['switch-organization', 'projects-get', 'switch-project'],
        },
        {
            features: ['error_tracking'],
            description: 'error tracking tools (underscore)',
            expectedTools: ['query-error-tracking-issues-list', 'query-error-tracking-issue'],
        },
        {
            features: ['error-tracking'],
            description: 'error tracking tools (hyphen, normalized)',
            expectedTools: ['query-error-tracking-issues-list', 'query-error-tracking-issue'],
        },
        {
            features: ['experiments'],
            description: 'experiment tools',
            expectedTools: ['experiment-list'],
        },
        {
            features: ['llm_analytics'],
            description: 'AI observability tools (underscore)',
            expectedTools: ['get-llm-total-costs-for-project'],
        },
        {
            features: ['llm-analytics'],
            description: 'AI observability tools (hyphen, normalized)',
            expectedTools: ['get-llm-total-costs-for-project'],
        },
        {
            features: ['docs'],
            description: 'documentation tools',
            expectedTools: ['docs-search'],
        },
        {
            features: ['invalid', 'flags'],
            description: 'valid tools when mixed with invalid features',
            expectedTools: ['feature-flag-get-definition'],
        },
        {
            features: ['invalid', 'unknown'],
            description: 'empty array for only invalid features',
            expectedTools: [],
        },
    ]

    describe('getToolsForFeatures', () => {
        it.each(featureTests)('should return $description', ({ features, expectedTools }) => {
            const tools = getToolsForFeatures({ features })

            for (const tool of expectedTools) {
                expect(tools).toContain(tool)
            }
        })

        it('should expose all annotation tools', () => {
            const tools = getToolsForFeatures({ features: ['annotations'] })

            expect(tools).toContain('annotation-create')
            expect(tools).toContain('annotation-delete')
            expect(tools).toContain('annotations-list')
            expect(tools).toContain('annotation-retrieve')
        })
    })
})

describe('Tool Filtering - Tools Allowlist', () => {
    describe('getToolsForFeatures with tools', () => {
        it('should return all tools when tools is undefined', () => {
            const allTools = getToolsForFeatures({})
            const withUndefinedTools = getToolsForFeatures({ tools: undefined })
            expect(withUndefinedTools).toEqual(allTools)
        })

        it('should return all tools when tools is empty array', () => {
            const allTools = getToolsForFeatures({})
            const withEmptyTools = getToolsForFeatures({ tools: [] })
            expect(withEmptyTools).toEqual(allTools)
        })

        it('should return only specified tools (plus always_available tools when enabled)', () => {
            const tools = getToolsForFeatures({
                tools: ['dashboard-get', 'dashboard-create'],
                featureFlags: { 'mcp-feedback-tool': true },
            })
            expect(tools).toContain('dashboard-get')
            expect(tools).toContain('dashboard-create')

            // always_available tools are included alongside the allowlist regardless of order
            // (when their gating feature flag is enabled).
            const alwaysAvailableTools = collectAlwaysAvailableToolNames()
            expect(tools).toContain('agent-feedback')

            // Every extra tool beyond the explicit allowlist must be always_available.
            const extras = tools.filter((name) => !['dashboard-get', 'dashboard-create'].includes(name))
            for (const extra of extras) {
                expect(alwaysAvailableTools).toContain(extra)
            }
        })

        it('should return only always_available tools for nonexistent tool names', () => {
            const tools = getToolsForFeatures({
                tools: ['nonexistent-tool'],
                featureFlags: { 'mcp-feedback-tool': true },
            })
            const alwaysAvailableTools = collectAlwaysAvailableToolNames()

            // The result is exactly the always_available set (order-independent).
            expect(tools).toContain('agent-feedback')
            expect(new Set(tools)).toEqual(new Set(alwaysAvailableTools))
        })

        it('should always include agent-feedback even when feature filter matches no tools', () => {
            const tools = getToolsForFeatures({
                features: ['nonexistent-feature'],
                featureFlags: { 'mcp-feedback-tool': true },
            })
            expect(tools).toContain('agent-feedback')
        })

        it('should hide agent-feedback when its gating feature flag is off', () => {
            // Flag explicitly off — tool is hidden even though it's always_available.
            const toolsWithFlagOff = getToolsForFeatures({ featureFlags: { 'mcp-feedback-tool': false } })
            expect(toolsWithFlagOff).not.toContain('agent-feedback')

            // No flags evaluated at all — also hidden (default behavior is `enable`).
            const toolsWithoutFlags = getToolsForFeatures({})
            expect(toolsWithoutFlags).not.toContain('agent-feedback')
        })

        it('should union with features (OR) when both are provided', () => {
            const tools = getToolsForFeatures({ features: ['flags'], tools: ['dashboard-get'] })

            // Should include flag tools from features
            expect(tools).toContain('feature-flag-get-definition')
            expect(tools).toContain('feature-flag-get-all')

            // Should also include the explicitly named tool
            expect(tools).toContain('dashboard-get')

            // Should not include unrelated tools
            expect(tools).not.toContain('insights-list')
        })

        it('should still apply readOnly on top of tools filter', () => {
            const tools = getToolsForFeatures({ tools: ['dashboard-get', 'dashboard-create'], readOnly: true })

            expect(tools).toContain('dashboard-get')
            expect(tools).not.toContain('dashboard-create')
        })

        it('should still apply aiConsentGiven on top of tools filter', () => {
            const withoutConsent = getToolsForFeatures({
                tools: ['dashboard-get', 'llma-summarization-create'],
                aiConsentGiven: false,
            })
            expect(withoutConsent).toContain('dashboard-get')
            expect(withoutConsent).not.toContain('llma-summarization-create')

            const withConsent = getToolsForFeatures({
                tools: ['dashboard-get', 'llma-summarization-create'],
                aiConsentGiven: true,
            })
            expect(withConsent).toContain('dashboard-get')
            expect(withConsent).toContain('llma-summarization-create')
        })
    })

    it('should combine tools with excludeTools via getToolsFromContext', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context, {
            tools: ['dashboard-get', 'dashboard-create', 'dashboard-delete'],
            excludeTools: ['dashboard-delete'],
        })
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-get')
        expect(toolNames).toContain('dashboard-create')
        expect(toolNames).not.toContain('dashboard-delete')
    })
})

const createMockContext = (scopes: string[]): Context => ({
    api: {} as any,
    cache: {} as any,
    env: {
        MCP_APPS_BASE_URL: undefined,
        POSTHOG_ANALYTICS_API_KEY: undefined,
        POSTHOG_ANALYTICS_HOST: undefined,
        POSTHOG_API_BASE_URL: undefined,
        POSTHOG_PUBLIC_URL: undefined,
        POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
        POSTHOG_UI_APPS_TOKEN: undefined,
    },
    stateManager: {
        getApiKey: async () => ({ scopes }),
        getAiConsentGiven: async () => undefined,
    } as any,
    sessionManager: new SessionManager({} as any),
    getDistinctId: async () => 'test-distinct-id',
    trackEvent: async () => {},
})

describe('Tool Filtering - API Scopes', () => {
    it('should return all tools when user has * scope', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-create')
        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('insight-query')
        expect(toolNames.length).toBeGreaterThan(25)
    })

    it('should only return dashboard tools when user has dashboard scopes', async () => {
        const context = createMockContext(['dashboard:read', 'dashboard:write'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-create')
        expect(toolNames).toContain('dashboard-get')
        expect(toolNames).toContain('dashboards-get-all')
        expect(toolNames).toContain('dashboard-reorder-tiles')

        expect(toolNames).not.toContain('create-feature-flag')
        expect(toolNames).not.toContain('organizations-list')
    })

    it('should include read tools when user has write scope', async () => {
        const context = createMockContext(['feature_flag:write'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('feature-flag-get-all')
        expect(toolNames).toContain('feature-flag-get-definition')

        expect(toolNames).not.toContain('dashboard-create')
    })

    it('should only return read tools when user has read scope', async () => {
        const context = createMockContext(['insight:read', 'query:read'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        // insight-query is in the hand-written TOOL_MAP and requires query:read
        expect(toolNames).toContain('insight-query')

        expect(toolNames).not.toContain('dashboard-create')
    })

    it('should return multiple scope tools when user has multiple scopes', async () => {
        const context = createMockContext(['dashboard:read', 'feature_flag:write', 'organization:read'])
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('dashboard-get')
        expect(toolNames).toContain('create-feature-flag')
        expect(toolNames).toContain('organization-get')

        expect(toolNames).not.toContain('dashboard-create')
        expect(toolNames).not.toContain('insight-create')
    })

    it('should return only tools with no required scopes when user has no matching scopes', async () => {
        const context = createMockContext(['some:unknown'])
        const tools = await getToolsFromContext(context, { featureFlags: { 'mcp-feedback-tool': true } })
        const toolNames = tools.map((t) => t.name)

        // Only tools with no required scopes (or that bypass scope checks) should be available.
        expect(toolNames).toContain('debug-mcp-ui-apps')
        expect(toolNames).toContain('agent-feedback')
        expectAllToolsHaveNoRequiredScopes(toolNames)
    })

    it('should return only tools with no required scopes when user has empty scopes', async () => {
        const context = createMockContext([])
        const tools = await getToolsFromContext(context, { featureFlags: { 'mcp-feedback-tool': true } })
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('debug-mcp-ui-apps')
        expect(toolNames).toContain('agent-feedback')
        expectAllToolsHaveNoRequiredScopes(toolNames)
    })
})

/**
 * Asserts that every tool in `toolNames` has an empty `required_scopes` array
 * in its definition. Used by the "user has no scopes" tests so they don't
 * break when a new no-scope utility tool is added.
 */
function expectAllToolsHaveNoRequiredScopes(toolNames: string[]): void {
    const definitions = getToolDefinitions()
    for (const name of toolNames) {
        const def = definitions[name]
        if (def === undefined) {
            // Hand-written tools like `insight-query` aren't always present in
            // the static definitions; the scope filter handles them separately.
            continue
        }
        expect(def.required_scopes).toEqual([])
    }
}

describe('OAUTH_SCOPES_SUPPORTED completeness', () => {
    // Minted directly into a server-issued token, never advertised via OAuth metadata
    // (mirrors INTERNAL_API_SCOPE_OBJECTS in posthog/scopes.py). Tools may require them, but
    // they are intentionally absent from OAUTH_SCOPES_SUPPORTED, so exclude them here.
    const SERVER_MINT_ONLY_SCOPES = new Set([
        'signal_scout_internal:read',
        'signal_scout_internal:write',
        'signal_scout_report:read',
        'signal_scout_report:write',
    ])

    // OAuth-hidden scopes (generated from OAUTH_HIDDEN_SCOPE_OBJECTS in posthog/scopes.py)
    // are PAT-grantable but never OAuth-advertised: tools requiring one (e.g. the staff-only
    // managed-migrations support tools) only surface for personal API keys carrying it.
    const oauthHiddenScopes = new Set<string>(OAUTH_HIDDEN_SCOPES)

    it('should include every scope referenced in tool definitions', () => {
        const supportedScopes = new Set<string>(OAUTH_SCOPES_SUPPORTED)

        const allDefinitions = getToolDefinitions()

        const scopesFromTools = new Set<string>()
        for (const def of Object.values(allDefinitions)) {
            for (const scope of def.required_scopes) {
                scopesFromTools.add(scope)
            }
        }

        const missing = [...scopesFromTools]
            .filter((s) => !supportedScopes.has(s) && !SERVER_MINT_ONLY_SCOPES.has(s) && !oauthHiddenScopes.has(s))
            .sort()

        expect(
            missing,
            `OAUTH_SCOPES_SUPPORTED is missing scopes used by tool definitions: ${missing.join(', ')}`
        ).toEqual([])
    })
})

describe('getAdvertisedOAuthScopes', () => {
    const supported = new Set<string>(OAUTH_SCOPES_SUPPORTED)
    const advertised = getAdvertisedOAuthScopes()
    const advertisedSet = new Set(advertised)

    it('stays a subset of OAUTH_SCOPES_SUPPORTED so nothing is rejected at /authorize', () => {
        const outside = advertised.filter((s) => !supported.has(s))
        expect(outside, `advertised scopes not grantable by the AS: ${outside.join(', ')}`).toEqual([])
    })

    it('keeps the identity scopes that ride every authorize', () => {
        for (const scope of OAUTH_SCOPES_SUPPORTED.filter((s) => !s.includes(':'))) {
            expect(advertisedSet.has(scope), `missing identity scope: ${scope}`).toBe(true)
        }
    })

    it('covers every grantable scope the tool catalog requires', () => {
        const required = new Set<string>()
        for (const def of Object.values(getToolDefinitions())) {
            for (const scope of def.required_scopes) {
                required.add(scope)
            }
        }
        const missing = [...required].filter((s) => supported.has(s) && !advertisedSet.has(s)).sort()
        expect(missing, `tool-required scopes dropped from the advertised list: ${missing.join(', ')}`).toEqual([])
    })

    it('narrows the full grantable set rather than mirroring it', () => {
        expect(advertised.length).toBeLessThan(OAUTH_SCOPES_SUPPORTED.length)
    })
})

describe('Tool Filtering - excludeTools', () => {
    const excludeTests = [
        {
            excludeTools: ['switch-organization', 'switch-project'],
            description: 'excludes both switch tools when project ID is provided',
            expectedExcluded: ['switch-organization', 'switch-project'],
            expectedIncluded: ['organizations-list', 'projects-get'],
        },
        {
            excludeTools: ['switch-organization'],
            description: 'excludes only switch-organization when org ID is provided',
            expectedExcluded: ['switch-organization'],
            expectedIncluded: ['switch-project', 'organizations-list', 'projects-get'],
        },
        {
            excludeTools: [],
            description: 'excludes nothing when empty array',
            expectedExcluded: [],
            expectedIncluded: ['switch-organization', 'switch-project'],
        },
        {
            excludeTools: undefined,
            description: 'excludes nothing when undefined',
            expectedExcluded: [],
            expectedIncluded: ['switch-organization', 'switch-project'],
        },
    ]

    it.each(excludeTests)('should $description', async ({ excludeTools, expectedExcluded, expectedIncluded }) => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context, { excludeTools })
        const toolNames = tools.map((t) => t.name)

        for (const tool of expectedExcluded) {
            expect(toolNames).not.toContain(tool)
        }
        for (const tool of expectedIncluded) {
            expect(toolNames).toContain(tool)
        }
    })

    it('should combine excludeTools with feature filtering', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context, {
            features: ['workspace'],
            excludeTools: ['switch-organization', 'switch-project'],
        })
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).toContain('projects-get')
        expect(toolNames).not.toContain('switch-organization')
        expect(toolNames).not.toContain('switch-project')
        expect(toolNames).not.toContain('dashboard-create')
    })
})

describe('Tool Filtering - AI Consent', () => {
    it('should exclude tools requiring AI consent when aiConsentGiven is false', () => {
        const tools = getToolsForFeatures({ aiConsentGiven: false })
        expect(tools).not.toContain('llma-summarization-create')
    })

    it('should include tools requiring AI consent when aiConsentGiven is true', () => {
        const tools = getToolsForFeatures({ aiConsentGiven: true })
        expect(tools).toContain('llma-summarization-create')
    })

    it('should exclude tools requiring AI consent when aiConsentGiven is undefined', () => {
        const tools = getToolsForFeatures({ aiConsentGiven: undefined })
        expect(tools).not.toContain('llma-summarization-create')
    })

    it('should not exclude tools that do not require AI consent when aiConsentGiven is false', () => {
        const tools = getToolsForFeatures({ aiConsentGiven: false })
        expect(tools).toContain('dashboard-get')
        expect(tools).toContain('feature-flag-get-all')
    })

    it('should combine aiConsentGiven with feature filtering', () => {
        const tools = getToolsForFeatures({ features: ['llm_analytics'], aiConsentGiven: false })
        expect(tools).not.toContain('llma-summarization-create')
        expect(tools).toContain('get-llm-total-costs-for-project')
    })

    it('should filter AI consent tools via getToolsFromContext when org denies consent', async () => {
        const context: Context = {
            api: {} as any,
            cache: {} as any,
            env: {
                MCP_APPS_BASE_URL: undefined,
                POSTHOG_ANALYTICS_API_KEY: undefined,
                POSTHOG_ANALYTICS_HOST: undefined,
                POSTHOG_API_BASE_URL: undefined,
                POSTHOG_PUBLIC_URL: undefined,
                POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                POSTHOG_UI_APPS_TOKEN: undefined,
            },
            stateManager: {
                getApiKey: async () => ({ scopes: ['*'] }),
                getAiConsentGiven: async () => false,
            } as any,
            sessionManager: new SessionManager({} as any),
            getDistinctId: async () => 'test-distinct-id',
            trackEvent: async () => {},
        }
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)
        expect(toolNames).not.toContain('llma-summarization-create')
        expect(toolNames).toContain('dashboard-get')
    })

    it('should include AI consent tools via getToolsFromContext when org approves consent', async () => {
        const context: Context = {
            api: {} as any,
            cache: {} as any,
            env: {
                MCP_APPS_BASE_URL: undefined,
                POSTHOG_ANALYTICS_API_KEY: undefined,
                POSTHOG_ANALYTICS_HOST: undefined,
                POSTHOG_API_BASE_URL: undefined,
                POSTHOG_PUBLIC_URL: undefined,
                POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                POSTHOG_UI_APPS_TOKEN: undefined,
            },
            stateManager: {
                getApiKey: async () => ({ scopes: ['*'] }),
                getAiConsentGiven: async () => true,
            } as any,
            sessionManager: new SessionManager({} as any),
            getDistinctId: async () => 'test-distinct-id',
            trackEvent: async () => {},
        }
        const tools = await getToolsFromContext(context)
        const toolNames = tools.map((t) => t.name)
        expect(toolNames).toContain('llma-summarization-create')
    })
})

describe('Tool Filtering - Scoped Teams', () => {
    // Tools whose `required_scopes` include an `organization:*` (or
    // `organization_member:*`, etc.) scope can't be exercised with a
    // project-scoped key — the backend 403s them. Hide from `tools/list` for
    // sessions whose token carries `scoped_teams`, surface them otherwise.
    it('hides tools requiring an org-scoped scope when scopedTeams is non-empty', () => {
        const tools = getToolsForFeatures({ scopedTeams: [42] })
        expect(tools).not.toContain('roles-list') // organization:read
        expect(tools).not.toContain('org-members-list') // organization_member:read
        expect(tools).not.toContain('organizations-list') // organization:read
        expect(tools).not.toContain('organization-get') // organization:read
        expect(tools).not.toContain('projects-get') // organization:read
    })

    it('keeps project-scoped tools visible when scopedTeams is non-empty', () => {
        const tools = getToolsForFeatures({ scopedTeams: [42] })
        expect(tools).toContain('dashboard-get')
        expect(tools).toContain('feature-flag-get-all')
    })

    it('keeps org-scope tools visible when scopedTeams is empty (unscoped token)', () => {
        const tools = getToolsForFeatures({ scopedTeams: [] })
        expect(tools).toContain('roles-list')
        expect(tools).toContain('organization-get')
    })

    it('keeps org-scope tools visible when scopedTeams is undefined', () => {
        const tools = getToolsForFeatures({ scopedTeams: undefined })
        expect(tools).toContain('roles-list')
        expect(tools).toContain('organization-get')
    })

    it('combines scopedTeams with feature filtering', () => {
        const tools = getToolsForFeatures({ features: ['workspace'], scopedTeams: [42] })
        expect(tools).not.toContain('organizations-list')
        expect(tools).not.toContain('organization-get')
    })
})

describe('Tool Filtering - Read-Only Mode', () => {
    it('should only return read-only tools when readOnly is true', () => {
        const tools = getToolsForFeatures({ readOnly: true })
        const definitions = getToolDefinitions()

        for (const toolName of tools) {
            const def = definitions[toolName] as ToolDefinition
            expect(def.annotations.readOnlyHint, `${toolName} should be readOnly`).toBe(true)
        }

        expect(tools).toContain('dashboard-get')
        expect(tools).toContain('dashboards-get-all')
        expect(tools).toContain('insights-list')
        expect(tools).not.toContain('dashboard-create')
        expect(tools).not.toContain('dashboard-delete')
        expect(tools).not.toContain('insight-create')
    })

    it('should return all tools when readOnly is false', () => {
        const allTools = getToolsForFeatures({})
        const readOnlyFalseTools = getToolsForFeatures({ readOnly: false })

        expect(readOnlyFalseTools).toEqual(allTools)
    })

    it('should return all tools when readOnly is undefined', () => {
        const allTools = getToolsForFeatures({})
        const readOnlyUndefinedTools = getToolsForFeatures({ readOnly: undefined })

        expect(readOnlyUndefinedTools).toEqual(allTools)
    })

    it('should combine readOnly with feature filtering', () => {
        const tools = getToolsForFeatures({ features: ['dashboards'], readOnly: true })

        expect(tools).toContain('dashboard-get')
        expect(tools).toContain('dashboards-get-all')
        expect(tools).not.toContain('dashboard-create')
        expect(tools).not.toContain('dashboard-delete')
        expect(tools).not.toContain('dashboard-update')
        expect(tools).not.toContain('feature-flag-get-all')
    })

    it('should combine readOnly with excludeTools via getToolsFromContext', async () => {
        const context = createMockContext(['*'])
        const tools = await getToolsFromContext(context, {
            readOnly: true,
            excludeTools: ['dashboard-get'],
        })
        const toolNames = tools.map((t) => t.name)

        expect(toolNames).not.toContain('dashboard-get')
        expect(toolNames).not.toContain('dashboard-create')
        expect(toolNames).toContain('dashboards-get-all')
    })
})

describe('Tool Filtering - Feature Flags', () => {
    const baseAnnotations = {
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
        readOnlyHint: true,
    }

    const baseDef: ToolDefinition = {
        description: 'test',
        category: 'Test',
        feature: 'test',
        summary: 'test',
        title: 'test',
        required_scopes: ['test:read'],
        annotations: baseAnnotations,
    }

    // We test the feature flag filtering logic by importing getToolsForFeatures
    // which internally calls getToolDefinitions. Since we can't easily mock the
    // module import in this ESM environment, we instead test the filtering logic
    // by adding feature-flagged entries into the real definitions. We use
    // getToolDefinitions() to get the real definitions, extend them with
    // feature-flagged tools, and then call the filter function with a wrapper.
    //
    // However, getToolsForFeatures calls getToolDefinitions internally, so we
    // need a different approach: directly test the filtering logic extracted
    // as a pure function.

    // Since getToolsForFeatures is tightly coupled to getToolDefinitions,
    // we'll test the filtering behavior by using real definitions plus
    // verifying the feature flag logic with tools that already exist.
    // We'll also add a tool definition with feature_flag to the real JSON
    // as a fixture.

    // Alternative: test the logic inline. getToolsForFeatures applies filters
    // to entries from getToolDefinitions. We can test the filter predicate
    // directly by examining what happens when we pass featureFlags to the
    // real getToolsForFeatures — since no real tool has feature_flag set,
    // featureFlags should have no effect on the real set.

    it('should not affect tools without feature_flag when featureFlags is provided', () => {
        const withoutFlags = getToolsForFeatures({})
        const withFlags = getToolsForFeatures({ featureFlags: { 'some-flag': true } })
        // No real tool has feature_flag, so results should be identical
        expect(withFlags).toEqual(withoutFlags)
    })

    it('should not affect tools without feature_flag when featureFlags is empty', () => {
        const withoutFlags = getToolsForFeatures({})
        const withFlags = getToolsForFeatures({ featureFlags: {} })
        expect(withFlags).toEqual(withoutFlags)
    })

    it('notebooks-collaboration flag flips the active notebook edit tool', () => {
        // When the flag is OFF, the legacy non-streaming PATCH tool is exposed.
        // When the flag is ON, it's hidden and the streaming collab edit tool
        // takes its place. The model never sees both at once.
        const off = getToolsForFeatures({ featureFlags: { 'notebooks-collaboration': false } })
        expect(off).toContain('notebooks-partial-update')
        expect(off).not.toContain('notebook-edit')

        const on = getToolsForFeatures({ featureFlags: { 'notebooks-collaboration': true } })
        expect(on).toContain('notebook-edit')
        expect(on).not.toContain('notebooks-partial-update')
    })

    it('getRequiredFeatureFlags should return flags used by current definitions', () => {
        const flags = getRequiredFeatureFlags()
        // Includes the gating flag for agent-feedback alongside the other gated tools.
        expect(flags).toEqual(
            expect.arrayContaining([
                'agent-platform',
                'logs-alerting',
                'logs-patterns-view',
                'replay-video-based-summarization',
                'tracing',
                'visual-review',
                'mcp-feedback-tool',
                'user-interviews',
                'customer-analytics-csp',
                'notebooks-collaboration',
                'replay-vision',
                'tasks',
                'dashboard-widgets',
                'heatmaps-mcp',
                'marketing-analytics-mcp',
                'product-business-knowledge',
                'field-notes',
                'mcp-analytics',
                'metrics',
                'endpoints-ai-materialization-fix',
                'engineering-analytics',
            ])
        )
        expect(flags).toHaveLength(21)
    })

    // Exercise the real predicate (toolPassesFlagGate) over hand-rolled entries
    // so we can cover variant / behavior / missing-flag matrices without
    // having to register fake tools into the global tool registry.
    describe('feature flag filter predicate', () => {
        function filterByFeatureFlags(entries: [string, ToolDefinition][], featureFlags?: EvaluatedFlags): string[] {
            return entries.filter(([_, def]) => toolPassesFlagGate(def, featureFlags)).map(([name]) => name)
        }

        it('should include tools with feature_flag when flag is enabled', () => {
            const entries: [string, ToolDefinition][] = [
                ['tool-a', { ...baseDef }],
                ['tool-b', { ...baseDef, feature_flag: 'flag-new-tool' }],
            ]
            const tools = filterByFeatureFlags(entries, { 'flag-new-tool': true })
            expect(tools).toContain('tool-a')
            expect(tools).toContain('tool-b')
        })

        it('should exclude tools with feature_flag when flag is disabled', () => {
            const entries: [string, ToolDefinition][] = [
                ['tool-a', { ...baseDef }],
                ['tool-b', { ...baseDef, feature_flag: 'flag-new-tool' }],
            ]
            const tools = filterByFeatureFlags(entries, { 'flag-new-tool': false })
            expect(tools).toContain('tool-a')
            expect(tools).not.toContain('tool-b')
        })

        it('should exclude enable-gated tools when no featureFlags provided', () => {
            const entries: [string, ToolDefinition][] = [
                ['tool-a', { ...baseDef }],
                ['tool-b', { ...baseDef, feature_flag: 'flag-new-tool' }],
            ]
            const tools = filterByFeatureFlags(entries)
            expect(tools).toContain('tool-a')
            expect(tools).not.toContain('tool-b')
        })

        it('should exclude enable-gated tools when flag is missing from evaluated map', () => {
            const entries: [string, ToolDefinition][] = [
                ['tool-a', { ...baseDef }],
                ['tool-b', { ...baseDef, feature_flag: 'flag-new-tool' }],
            ]
            const tools = filterByFeatureFlags(entries, {})
            expect(tools).toContain('tool-a')
            expect(tools).not.toContain('tool-b')
        })

        it('should hide tool with disable behavior when flag is enabled', () => {
            const entries: [string, ToolDefinition][] = [
                ['old-tool', { ...baseDef, feature_flag: 'flag-sunset', feature_flag_behavior: 'disable' }],
                ['new-tool', { ...baseDef, feature_flag: 'flag-sunset' }],
            ]
            const tools = filterByFeatureFlags(entries, { 'flag-sunset': true })
            expect(tools).not.toContain('old-tool')
            expect(tools).toContain('new-tool')
        })

        it('should show tool with disable behavior when flag is off', () => {
            const entries: [string, ToolDefinition][] = [
                ['old-tool', { ...baseDef, feature_flag: 'flag-sunset', feature_flag_behavior: 'disable' }],
                ['new-tool', { ...baseDef, feature_flag: 'flag-sunset' }],
            ]
            const tools = filterByFeatureFlags(entries, { 'flag-sunset': false })
            expect(tools).toContain('old-tool')
            expect(tools).not.toContain('new-tool')
        })

        it('should include disable-gated tools when no featureFlags provided', () => {
            const entries: [string, ToolDefinition][] = [
                ['old-tool', { ...baseDef, feature_flag: 'flag-sunset', feature_flag_behavior: 'disable' }],
            ]
            const tools = filterByFeatureFlags(entries)
            expect(tools).toContain('old-tool')
        })

        it('should support same flag enabling new tools and disabling old ones', () => {
            const entries: [string, ToolDefinition][] = [
                ['old-tool-v1', { ...baseDef, feature_flag: 'flag-experiment', feature_flag_behavior: 'disable' }],
                ['new-tool-v2', { ...baseDef, feature_flag: 'flag-experiment' }],
                ['unrelated-tool', { ...baseDef }],
            ]

            // Flag on: new tool visible, old tool hidden
            const toolsOn = filterByFeatureFlags(entries, { 'flag-experiment': true })
            expect(toolsOn).toContain('new-tool-v2')
            expect(toolsOn).not.toContain('old-tool-v1')
            expect(toolsOn).toContain('unrelated-tool')

            // Flag off: old tool visible, new tool hidden
            const toolsOff = filterByFeatureFlags(entries, { 'flag-experiment': false })
            expect(toolsOff).not.toContain('new-tool-v2')
            expect(toolsOff).toContain('old-tool-v1')
            expect(toolsOff).toContain('unrelated-tool')
        })
    })
})

describe('toolPassesEntitlementGate', () => {
    const gated = { feature_entitlement: 'audit_logs' } as ToolDefinition
    const ungated = {} as ToolDefinition

    it('passes tools with no feature_entitlement regardless of features', () => {
        expect(toolPassesEntitlementGate(ungated, [], true)).toBe(true)
        expect(toolPassesEntitlementGate(ungated, undefined, true)).toBe(true)
    })

    it('passes when the org has the entitlement on cloud', () => {
        expect(toolPassesEntitlementGate(gated, ['audit_logs', 'sso'], true)).toBe(true)
    })

    it('hides when cloud org positively lacks the entitlement', () => {
        expect(toolPassesEntitlementGate(gated, ['sso'], true)).toBe(false)
        expect(toolPassesEntitlementGate(gated, [], true)).toBe(false)
    })

    it('fails open on self-hosted (isCloud false)', () => {
        expect(toolPassesEntitlementGate(gated, [], false)).toBe(true)
    })

    it('fails open when entitlements are unknown', () => {
        expect(toolPassesEntitlementGate(gated, undefined, true)).toBe(true)
    })
})

describe('Tool Filtering - Entitlements (activity log family)', () => {
    // Guards the full YAML -> generated definitions -> getToolsForFeatures wire-up:
    // a predicate-only test wouldn't catch the entitlement missing from the
    // generated JSON for these specific tools.
    it('hides audit-log tools for a cloud org without audit_logs, shows them with it', () => {
        const withoutAudit = getToolsForFeatures({ availableFeatures: [], isCloud: true })
        expect(withoutAudit).not.toContain('advanced-activity-logs-list')
        expect(withoutAudit).not.toContain('advanced-activity-logs-filters')

        const withAudit = getToolsForFeatures({ availableFeatures: ['audit_logs'], isCloud: true })
        expect(withAudit).toContain('advanced-activity-logs-list')
        expect(withAudit).toContain('advanced-activity-logs-filters')

        // Fail-open: unresolved entitlements still advertise.
        const unknown = getToolsForFeatures({ isCloud: true })
        expect(unknown).toContain('advanced-activity-logs-list')
    })
})
