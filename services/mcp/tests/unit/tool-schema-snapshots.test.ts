import { mkdir, readdir, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { format } from 'oxfmt'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import type { Context } from '@/tools/types'

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
            getApiKey: async () => ({ scopes: ['*'] }),
            getAiConsentGiven: async () => true,
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

describe('Tool schema snapshots', () => {
    const __filename = fileURLToPath(import.meta.url)
    const __dirname = path.dirname(__filename)
    const context = createMockContext()
    it('snapshots runtime tool schemas', async () => {
        const shouldUpdateSnapshots = isSnapshotUpdateAll()
        const root = path.resolve(__dirname, '__snapshots__', 'tool-schemas')
        // Enable flag-gated tools we snapshot here: agent-feedback, tracing (APM spans), tasks,
        // dashboard-widgets. Other flag-gated tools (logs-alerts, visual-review, etc.) stay off to keep the surface stable.
        const featureFlags = {
            'mcp-feedback-tool': true,
            tracing: true,
            tasks: true,
            'dashboard-widgets': true,
            'agent-platform': true,
        }
        const tools = [...(await getToolsFromContext(context, { featureFlags }))].sort((a, b) =>
            a.name.localeCompare(b.name)
        )

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
})
