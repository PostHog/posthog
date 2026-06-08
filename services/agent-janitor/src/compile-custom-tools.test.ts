/**
 * Unit tests for the compile-at-freeze helper. Asserts the contract:
 *   - source.ts → compiled.js, written into the bundle, CJS module shape.
 *   - Multiple tools compile in one pass.
 *   - A syntax error in any tool aborts (errors[] populated, freeze caller
 *     must abort) — partial compilation is the wrong failure mode.
 *   - Tools whose `kind !== "custom"` are skipped.
 */

import type { S3Client } from '@aws-sdk/client-s3'
import { z } from 'zod'

import {
    AgentRevision,
    AgentSpecSchema,
    buildTestBundleStore,
    newTestPrefix,
    S3BundleStore,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { compileCustomToolsIntoBundle } from './compile-custom-tools'

let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore

beforeEach(() => {
    bundlePrefix = newTestPrefix('agent_bundles_compile_custom_tools_test')
    const built = buildTestBundleStore(bundlePrefix)
    bundleClient = built.client
    bundleStore = built.store
})

afterEach(async () => {
    await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
    bundleClient.destroy()
})

function mkRev(spec: Partial<z.input<typeof AgentSpecSchema>> = {}): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-27',
        state: 'draft',
        bundle_uri: 'mem://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({
            model: 'anthropic/claude-haiku-4-5',
            triggers: [{ type: 'chat', config: { require_auth: false } }],
            ...spec,
        }),
    }
}

describe('compileCustomToolsIntoBundle', () => {
    it('compiles a single custom tool source.ts into compiled.js (CJS shape)', async () => {
        await bundleStore.write(
            'rev1',
            'tools/my-tool/source.ts',
            `export default async function run(args: { name: string }) {
                return { greeting: 'hello ' + args.name }
            }`
        )
        const rev = mkRev({ tools: [{ kind: 'custom', id: 'my-tool', path: 'tools/my-tool' }] })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.errors).toEqual([])
        expect(result.compiled).toBe(1)

        const compiled = await bundleStore.readText('rev1', 'tools/my-tool/compiled.js')
        // CJS = exports.default-style. We don't assert the exact code esbuild
        // produces — just the shape contract: it's not the original TS, and
        // it references `exports`.
        expect(compiled).toContain('exports')
        expect(compiled).not.toContain('export default async function')
    })

    it('compiles N custom tools in one pass', async () => {
        await bundleStore.write(
            'rev1',
            'tools/a/source.ts',
            'export default async function run() { return { tool: "a" } }'
        )
        await bundleStore.write(
            'rev1',
            'tools/b/source.ts',
            'export default async function run() { return { tool: "b" } }'
        )
        const rev = mkRev({
            tools: [
                { kind: 'custom', id: 'a', path: 'tools/a' },
                { kind: 'custom', id: 'b', path: 'tools/b' },
            ],
        })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.errors).toEqual([])
        expect(result.compiled).toBe(2)
        expect(await bundleStore.exists('rev1', 'tools/a/compiled.js')).toBe(true)
        expect(await bundleStore.exists('rev1', 'tools/b/compiled.js')).toBe(true)
    })

    it('reports a structured error when source.ts has a syntax error — does not write compiled.js for the broken tool', async () => {
        await bundleStore.write('rev1', 'tools/ok/source.ts', 'export default async function run() { return {} }')
        await bundleStore.write(
            'rev1',
            'tools/broken/source.ts',
            'export default async function run( { return {} }' // missing close paren
        )
        const rev = mkRev({
            tools: [
                { kind: 'custom', id: 'ok', path: 'tools/ok' },
                { kind: 'custom', id: 'broken', path: 'tools/broken' },
            ],
        })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.errors).toHaveLength(1)
        expect(result.errors[0]).toMatchObject({
            tool_id: 'broken',
            source_path: 'tools/broken/source.ts',
        })
        expect(result.errors[0].message).toBeTruthy()
        // The good tool DID compile (we don't roll back) — the caller is
        // responsible for aborting freeze. This lets the caller surface the
        // exact failing tool to the user without us pretending a partial
        // bundle is the wrong shape.
        expect(await bundleStore.exists('rev1', 'tools/ok/compiled.js')).toBe(true)
        expect(await bundleStore.exists('rev1', 'tools/broken/compiled.js')).toBe(false)
    })

    it('skips non-custom tool refs (native, client) silently', async () => {
        await bundleStore.write('rev1', 'tools/my-tool/source.ts', 'export default async function run() { return {} }')
        const rev = mkRev({
            tools: [
                { kind: 'native', id: '@posthog/web-fetch' },
                { kind: 'custom', id: 'my-tool', path: 'tools/my-tool' },
            ],
        })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.compiled).toBe(1) // only the custom one
        expect(result.errors).toEqual([])
    })

    it('returns { compiled: 0, errors: [] } when no custom tools are declared', async () => {
        const rev = mkRev({ tools: [{ kind: 'native', id: '@posthog/web-fetch' }] })
        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result).toEqual({ compiled: 0, errors: [] })
    })
})
