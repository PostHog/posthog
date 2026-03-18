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
            INKEEP_API_KEY: 'test-key',
            MCP_APPS_BASE_URL: undefined,
            POSTHOG_ANALYTICS_API_KEY: undefined,
            POSTHOG_ANALYTICS_HOST: undefined,
            POSTHOG_API_BASE_URL: undefined,
            MCP_APPS_BASE_URL: undefined,
            POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
            POSTHOG_UI_APPS_TOKEN: undefined,
        },
        stateManager: {
            getApiKey: async () => ({ scopes: ['*'] }),
            getAiConsentGiven: async () => true,
        } as any,
        sessionManager: new SessionManager({} as any),
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

type SnapshotBucket = 'common' | 'v1' | 'v2'

type SnapshotEntry = {
    toolName: string
    bucket: SnapshotBucket
    schema: unknown
}

async function listSnapshotFiles(root: string): Promise<string[]> {
    const buckets: SnapshotBucket[] = ['common', 'v1', 'v2']
    const all: string[] = []

    for (const bucket of buckets) {
        const dir = path.join(root, bucket)
        try {
            const files = await readdir(dir)
            for (const file of files) {
                if (file.endsWith('.json')) {
                    all.push(path.join(dir, file))
                }
            }
        } catch {
            // Directory might not exist yet.
        }
    }

    return all
}

function stableStringify(value: unknown): string {
    return JSON.stringify(value)
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
    it('snapshots runtime tool schemas as common + version deltas', async () => {
        const shouldUpdateSnapshots = isSnapshotUpdateAll()
        const root = path.resolve(__dirname, '__snapshots__', 'tool-schemas')
        const v1Tools = [...(await getToolsFromContext(context, { version: 1 }))].sort((a, b) =>
            a.name.localeCompare(b.name)
        )
        const v2Tools = [...(await getToolsFromContext(context, { version: 2 }))].sort((a, b) =>
            a.name.localeCompare(b.name)
        )

        const v1Schemas = new Map<string, unknown>()
        const v2Schemas = new Map<string, unknown>()

        for (const tool of v1Tools) {
            const jsonSchema = z.toJSONSchema(tool.schema, { io: 'input', reused: 'inline' })
            v1Schemas.set(tool.name, deepSortKeys(jsonSchema))
        }
        for (const tool of v2Tools) {
            const jsonSchema = z.toJSONSchema(tool.schema, { io: 'input', reused: 'inline' })
            v2Schemas.set(tool.name, deepSortKeys(jsonSchema))
        }

        const allNames = [...new Set([...v1Schemas.keys(), ...v2Schemas.keys()])].sort()
        const entries: SnapshotEntry[] = []

        for (const toolName of allNames) {
            const v1 = v1Schemas.get(toolName)
            const v2 = v2Schemas.get(toolName)

            if (v1 && v2) {
                if (stableStringify(v1) === stableStringify(v2)) {
                    entries.push({ toolName, bucket: 'common', schema: v1 })
                } else {
                    entries.push({ toolName, bucket: 'v1', schema: v1 })
                    entries.push({ toolName, bucket: 'v2', schema: v2 })
                }
            } else if (v1) {
                entries.push({ toolName, bucket: 'v1', schema: v1 })
            } else if (v2) {
                entries.push({ toolName, bucket: 'v2', schema: v2 })
            }
        }

        const commonCount = entries.filter((entry) => entry.bucket === 'common').length
        expect(commonCount).toBeGreaterThan(0)

        for (const bucket of ['common', 'v1', 'v2'] as const) {
            await mkdir(path.join(root, bucket), { recursive: true })
        }

        const expectedPaths = new Set<string>()

        for (const entry of entries) {
            const snapshotPath = path.join(root, entry.bucket, `${entry.toolName}.json`)
            expectedPaths.add(snapshotPath)
            const content = await formatSnapshotJson(snapshotPath, entry.schema)
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
