import { mkdir, readdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { isDeepStrictEqual } from 'node:util'
import { format } from 'oxfmt'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { PostHogMCP } from '@posthog/mcp-analytics'

import { dedupeRepeatedDescriptions, toMcpInputSchema } from '@/hono/tool-catalog'
import { CLAUDE_REGISTRY_INPUT_SCHEMA_CHAR_LIMIT, OAUTH_SCOPES_HIDDEN } from '@/lib/constants'
import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

function createMockContext(): Context {
    return {
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
            // Staff-only tools require their OAuth-hidden scope explicitly on the key
            // (`*` alone does not match) plus a staff user, so grant both here to keep
            // their schemas in the snapshot surface.
            getApiKey: async () => ({ scopes: ['*', ...OAUTH_SCOPES_HIDDEN, 'signal_scout_monitoring:write'] }),
            getAiConsentGiven: async () => true,
            getUser: async () => ({ is_staff: true }),
        } as any,
        sessionManager: new SessionManager({} as any),
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function deepSortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map((item) => deepSortKeys(item))
    }

    if (value && typeof value === 'object') {
        const obj = value as Record<string, unknown>
        const sortedEntries = Object.entries(obj)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([key, nestedValue]) => [key, deepSortKeys(nestedValue)] as const)
        return Object.fromEntries(sortedEntries)
    }

    return value
}

async function listSnapshotFiles(root: string): Promise<string[]> {
    try {
        const files = await readdir(root)
        return files.filter((file) => file.endsWith('.json')).map((file) => path.join(root, file))
    } catch {
        // Directory might not exist yet.
        return []
    }
}

function isSnapshotUpdateAll(): boolean {
    // Vitest strips CLI flags from process.argv in worker threads, so we read
    // the snapshot-update mode from vitest's internal state instead.
    const state = expect.getState() as unknown as { snapshotState?: { _updateSnapshot?: string } }
    return state.snapshotState?._updateSnapshot === 'all'
}

async function formatSnapshotJson(snapshotPath: string, schema: unknown): Promise<string> {
    const content = `${JSON.stringify(schema, null, 4)}\n`
    const result = await format(snapshotPath, content, { tabWidth: 4, printWidth: 120 })

    if (result.errors.length > 0) {
        const errorMessage = result.errors.map((error) => error.message ?? 'unknown formatting error').join('; ')
        throw new Error(`Failed formatting snapshot ${snapshotPath}: ${errorMessage}`)
    }

    return result.code
}

async function loadSnapshotTools(): Promise<Tool<ZodObjectAny>[]> {
    // Enable flag-gated tools we snapshot here: tracing (APM spans), tasks, loops,
    // experiment setup context. Other flag-gated tools (logs-alerts,
    // visual-review, etc.) stay off to keep the surface stable.
    // agent-feedback is always_available and no longer flag-gated, so it appears regardless.
    const featureFlags = {
        tracing: true,
        'logs-agent-tools': true,
        tasks: true,
        'tasks-mcp-agent-run-start': true,
        loops: true,
        'agent-platform': true,
        'experiment-setup-context': true,
        'scout-trials': true,
        'signals-report-checks-replace': true,
        'inbox-report-actions-mcp': true,
        'signals-reviewer-exclusions-mcp': true,
        'ai-observability-offline-evaluations': true,
        'workflows-supabase-auth-emails': true,
        'warehouse-suggestions': true,
        'workflows-destination-suggestion': true,
        'scouts-tool-access': true,
        'subscription-source-summaries': true,
        'marketing-analytics-conversion-setup-ai': true,
        'marketing-analytics-recommendations': true,
        'workflows-mcp-onboarding': true,
        'workflows-sending-tier-requests': true,
        'insight-data-checks': true,
        'workflows-transactional-email-api': true,
        'activity-summary': true,
        'activity-summary-search': true,
        'personal-inbox-ranking': true,
        'aeo-citation-tracking': true,
        'mcp-session-recording-console-logs': true,
        'anomalies-search': true,
        'warehouse-multi-destination': true,
        'feature-flag-rules-v2-mcp': true,
        'support-macros': true,
    }
    return [...(await getToolsFromContext(createMockContext(), { featureFlags }))].sort((a, b) =>
        a.name.localeCompare(b.name)
    )
}

describe('Tool schema snapshots', () => {
    const __filename = fileURLToPath(import.meta.url)
    const __dirname = path.dirname(__filename)
    it('snapshots runtime tool schemas', async () => {
        const shouldUpdateSnapshots = isSnapshotUpdateAll()
        const root = path.resolve(__dirname, '__snapshots__', 'tool-schemas')
        const tools = await loadSnapshotTools()

        expect(tools.length).toBeGreaterThan(0)

        await mkdir(root, { recursive: true })

        const expectedPaths = new Set<string>()

        for (const tool of tools) {
            const jsonSchema = deepSortKeys(z.toJSONSchema(tool.schema, { io: 'input', reused: 'inline' }))
            const snapshotPath = path.join(root, `${tool.name}.json`)
            expectedPaths.add(snapshotPath)
            const content = await formatSnapshotJson(snapshotPath, jsonSchema)
            await expect(content).toMatchFileSnapshot(snapshotPath)
        }

        const existingPaths = await listSnapshotFiles(root)
        const stalePaths = existingPaths.filter((existingPath) => !expectedPaths.has(existingPath)).sort()

        if (shouldUpdateSnapshots) {
            for (const stalePath of stalePaths) {
                await rm(stalePath)
            }
        } else if (stalePaths.length > 0) {
            throw new Error(
                `Found stale snapshot files (run vitest -u to clean them):\n${stalePaths
                    .map((file) => `- ${file}`)
                    .join('\n')}`
            )
        }
    })

    describe('schema budgets', () => {
        // Ratchet: the number of oversized tool schemas may only go down.
        const OVERSIZED_SCHEMA_COUNT = 39
        // Ratchet: the share of nested properties with a description may only go up.
        const NESTED_DESCRIPTION_COVERAGE_FLOOR_PERCENT = 55
        const TOOL_SCHEMA_CHAR_BUDGET = 40_000
        // Ratchet: existing offenders at their size rounded up to 1,000 chars. Never add a tool here.
        const OVERSIZED_TOOL_SCHEMA_CEILINGS: Record<string, number> = {
            'experiment-update': 99_000,
            'project-settings-update': 75_000,
            'experiment-create': 65_000,
            'query-trends-actors': 65_000,
            'query-trends': 63_000,
            'query-funnel-actors': 54_000,
            'query-funnel': 51_000,
            'query-retention-actors': 47_000,
            'query-retention': 46_000,
        }
        // About 1% over the measured total, so help_text edits pass and new tools need a reviewed raise.
        const TOOLS_MODE_ROSTER_CHAR_BUDGET = 3_920_000

        interface DescriptionCoverage {
            described: number
            total: number
        }

        function schemaChildren(schema: Record<string, unknown>): Record<string, unknown>[] {
            const branches = [schema.anyOf, schema.oneOf, schema.allOf].flatMap((group) =>
                Array.isArray(group) ? (group as Record<string, unknown>[]) : []
            )
            const items =
                schema.items && typeof schema.items === 'object' ? [schema.items as Record<string, unknown>] : []
            return [...branches, ...items]
        }

        function countNestedProperties(schema: unknown, depth: number, into: DescriptionCoverage): void {
            if (!schema || typeof schema !== 'object') {
                return
            }
            const node = schema as Record<string, unknown>
            const properties = node.properties as Record<string, Record<string, unknown>> | undefined
            for (const property of Object.values(properties ?? {})) {
                if (depth > 0) {
                    into.total += 1
                    if (typeof property.description === 'string' && property.description.length > 0) {
                        into.described += 1
                    }
                }
                countNestedProperties(property, depth + 1, into)
            }
            for (const child of schemaChildren(node)) {
                countNestedProperties(child, depth, into)
            }
        }

        function percent({ described, total }: DescriptionCoverage): number {
            return total === 0 ? 100 : (described / total) * 100
        }

        interface AdvertisedSchemaSize {
            name: string
            size: number
        }

        // The analytics SDK adds a `context` property at registration, so measure the registered shape.
        async function advertisedSchemaSizes(): Promise<AdvertisedSchemaSize[]> {
            const tools = await loadSnapshotTools()
            const posthog = new PostHogMCP('phc_test', { disabled: true })
            return posthog
                .prepareToolList(
                    tools.map((tool) => ({
                        name: tool.name,
                        description: tool.description,
                        inputSchema: toMcpInputSchema(tool.schema),
                    }))
                )
                .map((entry) => ({ name: entry.name, size: JSON.stringify(entry.inputSchema).length }))
                .sort((a, b) => b.size - a.size)
        }

        function withoutDescriptions(value: unknown): unknown {
            if (Array.isArray(value)) {
                return value.map(withoutDescriptions)
            }
            if (value && typeof value === 'object') {
                return Object.fromEntries(
                    Object.entries(value)
                        .filter(([key, nested]) => !(key === 'description' && typeof nested === 'string'))
                        .map(([key, nested]) => [key, withoutDescriptions(nested)])
                )
            }
            return value
        }

        it('advertises schemas that differ from the zod rendering only in descriptions', async () => {
            const tools = await loadSnapshotTools()
            const changed = tools
                .filter((tool) => {
                    const rendered = z.toJSONSchema(tool.schema, { io: 'input', target: 'draft-7' }) as Record<
                        string,
                        unknown
                    >
                    const advertised = dedupeRepeatedDescriptions({ ...rendered })
                    return !isDeepStrictEqual(withoutDescriptions(advertised), withoutDescriptions(rendered))
                })
                .map((tool) => tool.name)

            expect(changed).toEqual([])
        })

        it('keeps each advertised tool schema within its size budget', async () => {
            const sizes = await advertisedSchemaSizes()
            const overBudget = sizes.filter(
                ({ name, size }) => size > (OVERSIZED_TOOL_SCHEMA_CEILINGS[name] ?? TOOL_SCHEMA_CHAR_BUDGET)
            )
            const belowBudget = Object.keys(OVERSIZED_TOOL_SCHEMA_CEILINGS).filter(
                (name) => (sizes.find((entry) => entry.name === name)?.size ?? 0) <= TOOL_SCHEMA_CHAR_BUDGET
            )

            expect(
                overBudget,
                `These tool schemas grew past their budget of ${TOOL_SCHEMA_CHAR_BUDGET} chars, or past their ceiling ` +
                    `in OVERSIZED_TOOL_SCHEMA_CEILINGS. Tools mode sends every schema on each tools/list. Shrink the ` +
                    `schema with exclude_params, include_params or param_overrides in the product tools.yaml, or ` +
                    `shorten serializer help_text.`
            ).toEqual([])
            expect(
                belowBudget,
                `These tools are now within ${TOOL_SCHEMA_CHAR_BUDGET} chars. Remove them from OVERSIZED_TOOL_SCHEMA_CEILINGS.`
            ).toEqual([])
        })

        it('keeps the total tools-mode roster within its budget', async () => {
            const sizes = await advertisedSchemaSizes()
            const total = sizes.reduce((sum, { size }) => sum + size, 0)

            expect(
                total,
                `The advertised tool schemas total ${total} chars, over TOOLS_MODE_ROSTER_CHAR_BUDGET ` +
                    `(${TOOLS_MODE_ROSTER_CHAR_BUDGET}). Tools-mode clients receive all of them on every session. ` +
                    `Shrink schemas, or raise the budget in this PR so a reviewer accepts the growth.`
            ).toBeLessThanOrEqual(TOOLS_MODE_ROSTER_CHAR_BUDGET)
        })

        it('keeps the number of tool schemas over the claude.ai registry limit from growing', async () => {
            const oversized = (await advertisedSchemaSizes()).filter(
                ({ size }) => size >= CLAUDE_REGISTRY_INPUT_SCHEMA_CHAR_LIMIT
            )
            const offenders = oversized.map(({ name, size }) => `- ${name}: ${size} chars`).join('\n')

            expect(
                oversized.length,
                `${oversized.length} tool schemas are at or over ${CLAUDE_REGISTRY_INPUT_SCHEMA_CHAR_LIMIT} chars, ` +
                    `above the ratchet of ${OVERSIZED_SCHEMA_COUNT}. Claude web and desktop silently drop such tools in tools mode. ` +
                    `Shrink the schema with exclude_params, include_params or param_overrides in the product tools.yaml, ` +
                    `or shorten serializer help_text. Largest schemas:\n${offenders}`
            ).toBeLessThanOrEqual(OVERSIZED_SCHEMA_COUNT)
            expect(
                oversized.length,
                `Only ${oversized.length} tool schemas are at or over the limit. Lower OVERSIZED_SCHEMA_COUNT ` +
                    `from ${OVERSIZED_SCHEMA_COUNT} to ${oversized.length} so the count only goes down.`
            ).toBe(OVERSIZED_SCHEMA_COUNT)
        })

        it('keeps description coverage of nested tool properties from dropping', async () => {
            const tools = await loadSnapshotTools()
            const nested: DescriptionCoverage = { described: 0, total: 0 }
            for (const tool of tools) {
                const schema = z.toJSONSchema(tool.schema, { io: 'input', reused: 'inline' })
                countNestedProperties(schema, 0, nested)
            }
            expect(
                percent(nested),
                `Only ${percent(nested).toFixed(1)}% of nested tool properties have a description ` +
                    `(${nested.described} of ${nested.total}), below the floor of ${NESTED_DESCRIPTION_COVERAGE_FLOOR_PERCENT}%. ` +
                    `Add help_text to the serializer fields behind the new properties and regenerate with hogli build:openapi, ` +
                    `or drop the properties with exclude_params.`
            ).toBeGreaterThanOrEqual(NESTED_DESCRIPTION_COVERAGE_FLOOR_PERCENT)
        })
    })
})
