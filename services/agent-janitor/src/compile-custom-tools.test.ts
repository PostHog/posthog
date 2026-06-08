/**
 * Unit tests for the compile-at-freeze helper. Asserts the contract:
 *   - source.ts → compiled.js, written into the bundle, CJS module shape.
 *   - Multiple tools compile in one pass.
 *   - A syntax error in any tool aborts (errors[] populated, freeze caller
 *     must abort) — partial compilation is the wrong failure mode.
 *   - Tools whose `kind !== "custom"` are skipped.
 *   - Compiled output is shape-checked: the runner requires
 *     `{ actions: { default: fn } }`. A source.ts that compiles cleanly
 *     but exports the wrong shape is rejected at freeze instead of at
 *     session-start (live agent, opaque failure mid-chat).
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

// The canonical source.ts shape — matches what the runner's sandbox loader
// expects: `module.exports.default ?? module.exports → { id?, actions: { default: fn } }`.
// Every passing-shape test uses this template (with the body swapped) so a
// single drift in the contract surfaces in one place.
const GOOD_SOURCE = (body: string): string =>
    `
export default {
    actions: {
        default: async (args: { name?: string }) => (${body}),
    },
}
`.trim()

describe('compileCustomToolsIntoBundle', () => {
    it('compiles a single custom tool source.ts into compiled.js (CJS shape)', async () => {
        await bundleStore.write('rev1', 'tools/my-tool/source.ts', GOOD_SOURCE(`{ greeting: 'hello ' + args.name }`))
        const rev = mkRev({ tools: [{ kind: 'custom', id: 'my-tool', path: 'tools/my-tool' }] })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.errors).toEqual([])
        expect(result.compiled).toBe(1)

        const compiled = await bundleStore.readText('rev1', 'tools/my-tool/compiled.js')
        // CJS = exports.default-style. We don't assert the exact code esbuild
        // produces — just the shape contract: it's not the original TS, and
        // it references `exports`.
        expect(compiled).toContain('exports')
        expect(compiled).not.toContain('export default {')
    })

    it('compiles N custom tools in one pass', async () => {
        await bundleStore.write('rev1', 'tools/a/source.ts', GOOD_SOURCE(`{ tool: 'a' }`))
        await bundleStore.write('rev1', 'tools/b/source.ts', GOOD_SOURCE(`{ tool: 'b' }`))
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
        await bundleStore.write('rev1', 'tools/ok/source.ts', GOOD_SOURCE(`{}`))
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
        await bundleStore.write('rev1', 'tools/my-tool/source.ts', GOOD_SOURCE(`{}`))
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

    // Shape-mismatch cases. Each is a source.ts that parses cleanly but
    // produces a compiled.js the runner can't dispatch. The whole point of
    // the freeze-time shape check is catching these BEFORE the agent goes
    // live and the failure surfaces mid-conversation as `action_not_found`.
    it.each([
        {
            label: 'bare function (the historical concierge foot-gun)',
            source: 'export default async function run() { return {} }',
            expectedFragment: 'must export `{ id?, actions: { default: fn } }`',
        },
        {
            label: 'object missing `actions`',
            source: 'export default { id: "x", run: async () => ({}) }',
            expectedFragment: '`actions` is missing or not an object',
        },
        {
            label: '`actions` present but no `default` key',
            source: 'export default { actions: { run: async () => ({}) } }',
            expectedFragment: '`actions.default` as a function',
        },
        {
            label: '`actions.default` is a string instead of a function',
            source: 'export default { actions: { default: "not a function" } }',
            expectedFragment: '`actions.default` as a function',
        },
    ])('rejects shape mismatch: $label', async ({ source, expectedFragment }) => {
        await bundleStore.write('rev1', 'tools/bad/source.ts', source)
        const rev = mkRev({ tools: [{ kind: 'custom', id: 'bad', path: 'tools/bad' }] })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.compiled).toBe(0)
        expect(result.errors).toHaveLength(1)
        expect(result.errors[0]).toMatchObject({
            tool_id: 'bad',
            source_path: 'tools/bad/source.ts',
        })
        expect(result.errors[0].message).toContain(expectedFragment)
        // Critically: compiled.js is NOT written on shape failure. Otherwise
        // the next freeze would see a stale broken compiled.js (esbuild
        // failure path would skip it, but a successful esbuild + shape
        // failure must not leave junk behind).
        expect(await bundleStore.exists('rev1', 'tools/bad/compiled.js')).toBe(false)
    })

    it('accepts `actions.default` as a { run } wrapper object — runner supports both', async () => {
        await bundleStore.write(
            'rev1',
            'tools/wrapper/source.ts',
            `export default { actions: { default: { run: async () => ({ ok: true }) } } }`
        )
        const rev = mkRev({ tools: [{ kind: 'custom', id: 'wrapper', path: 'tools/wrapper' }] })

        const result = await compileCustomToolsIntoBundle(rev, bundleStore)
        expect(result.errors).toEqual([])
        expect(result.compiled).toBe(1)
    })
})
