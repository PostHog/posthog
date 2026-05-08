import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import { ApiClient, type MappedProductKey, QUERY_KIND_TO_PRODUCT_KEY, injectProductKey } from '@/api/client'

const REPO_ROOT = resolve(__dirname, '../../../..')
const SCHEMA_GENERAL_PATH = resolve(REPO_ROOT, 'frontend/src/queries/schema/schema-general.ts')
const QUERY_WRAPPERS_PATH = resolve(REPO_ROOT, 'services/mcp/src/tools/generated/query-wrappers.ts')

// Parse `export enum ProductKey { ... }` block from schema-general.ts and extract the
// string values. Reading the source file (rather than importing the module) avoids
// pulling the entire frontend graph into the MCP test bundle.
function parseFrontendProductKeys(): Set<string> {
    const source = readFileSync(SCHEMA_GENERAL_PATH, 'utf8')
    const match = /export enum ProductKey \{([\s\S]*?)\n\}/.exec(source)
    if (!match) {
        throw new Error(`Could not locate ProductKey enum in ${SCHEMA_GENERAL_PATH}`)
    }
    const values = new Set<string>()
    for (const line of match[1]!.split('\n')) {
        const valueMatch = /^\s*[A-Z0-9_]+\s*=\s*'([^']+)'/.exec(line)
        if (valueMatch) {
            values.add(valueMatch[1]!)
        }
    }
    return values
}

// Extract every `kind: '...'` literal registered under `GENERATED_TOOLS` in
// query-wrappers.ts. These are the runtime kinds MCP actually sends to /query/,
// so any kind in this set that isn't covered by QUERY_KIND_TO_PRODUCT_KEY would
// silently attribute to product=mcp.
function parseGeneratedToolKinds(): Set<string> {
    const source = readFileSync(QUERY_WRAPPERS_PATH, 'utf8')
    const generatedToolsMatch = /export const GENERATED_TOOLS[\s\S]*?\n\}\n/.exec(source)
    if (!generatedToolsMatch) {
        throw new Error(`Could not locate GENERATED_TOOLS block in ${QUERY_WRAPPERS_PATH}`)
    }
    const kinds = new Set<string>()
    const re = /kind:\s*'([A-Z][A-Za-z0-9]*Query)'/g
    let m: RegExpExecArray | null
    while ((m = re.exec(generatedToolsMatch[0])) !== null) {
        kinds.add(m[1]!)
    }
    return kinds
}

describe('injectProductKey', () => {
    const taggedEntries = Object.entries(QUERY_KIND_TO_PRODUCT_KEY).filter(
        (entry): entry is [string, MappedProductKey] => entry[1] !== null
    )
    const untaggedEntries = Object.entries(QUERY_KIND_TO_PRODUCT_KEY).filter(([, v]) => v === null)

    it.each(taggedEntries)('tags %s with productKey=%s', (kind, expected) => {
        const result = injectProductKey({ kind })
        expect(result).toEqual({ kind, tags: { productKey: expected } })
    })

    it.each(untaggedEntries)('leaves %s untagged (null entry)', (kind) => {
        expect(injectProductKey({ kind })).toEqual({ kind })
    })

    it('returns the query unchanged when kind is missing', () => {
        const query = { foo: 'bar' }
        expect(injectProductKey(query)).toBe(query)
    })

    it('returns the query unchanged for an unknown kind', () => {
        const query = { kind: 'TotallyMadeUpQuery' }
        expect(injectProductKey(query)).toBe(query)
    })

    it('preserves a caller-supplied productKey instead of overwriting it', () => {
        const query = { kind: 'TrendsQuery', tags: { productKey: 'web_analytics', scene: 'WebAnalytics' } }
        expect(injectProductKey(query)).toBe(query)
    })

    it('merges into existing tags when productKey is absent', () => {
        const result = injectProductKey({ kind: 'TrendsQuery', tags: { scene: 'Insight' } })
        expect(result).toEqual({
            kind: 'TrendsQuery',
            tags: { scene: 'Insight', productKey: 'product_analytics' },
        })
    })

    it.each([[[]], [['scene']], [42], ['nope'], [true]] as const)(
        'leaves the query untouched when tags is a non-object shape: %p',
        (tags) => {
            const query = { kind: 'TrendsQuery', tags }
            expect(injectProductKey(query)).toBe(query)
        }
    )
})

describe('ActorsQuery wrapper top-level tags propagation', () => {
    it('propagates the source productKey to the wrapped ActorsQuery so the backend tags it', async () => {
        const fetchSpy = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ results: [], hasMore: false, offset: 0 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        )
        vi.stubGlobal('fetch', fetchSpy)

        try {
            const client = new ApiClient({ apiToken: 'token', baseUrl: 'https://example.com' })
            await client.query({ projectId: '1' }).trendsActors({
                query: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } },
            })

            expect(fetchSpy).toHaveBeenCalledOnce()
            const [, options] = fetchSpy.mock.calls[0]!
            const body = JSON.parse(options.body as string)
            expect(body.query.kind).toBe('ActorsQuery')
            // Top-level tags so `_infer_query_tags` (which only inspects the outer query) finds it.
            expect(body.query.tags).toEqual({ productKey: 'product_analytics' })
            // Source is also tagged so any nested runner that re-reads the source still sees it.
            expect(body.query.source.tags).toEqual({ productKey: 'product_analytics' })
        } finally {
            vi.unstubAllGlobals()
        }
    })

    it('omits top-level tags when the source kind is unmapped (no silent attribution)', async () => {
        const fetchSpy = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ results: [], hasMore: false, offset: 0 }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        )
        vi.stubGlobal('fetch', fetchSpy)

        try {
            const client = new ApiClient({ apiToken: 'token', baseUrl: 'https://example.com' })
            await client.query({ projectId: '1' }).trendsActors({
                query: { kind: 'TotallyUnknownActorsSource' },
            })

            const [, options] = fetchSpy.mock.calls[0]!
            const body = JSON.parse(options.body as string)
            expect(body.query.tags).toBeUndefined()
        } finally {
            vi.unstubAllGlobals()
        }
    })
})

describe('QUERY_KIND_TO_PRODUCT_KEY drift guards', () => {
    it('every mapped productKey exists in the canonical frontend ProductKey enum', () => {
        const canonical = parseFrontendProductKeys()
        // Sanity check the parser: if this fires, the enum format changed, not the map.
        expect(canonical.size).toBeGreaterThan(20)

        const offenders: Array<[string, string]> = []
        for (const [kind, productKey] of Object.entries(QUERY_KIND_TO_PRODUCT_KEY)) {
            if (productKey !== null && !canonical.has(productKey)) {
                offenders.push([kind, productKey])
            }
        }
        expect(offenders).toEqual([])
    })

    it('every kind registered in GENERATED_TOOLS is covered by the map', () => {
        const generatedKinds = parseGeneratedToolKinds()
        // Sanity check the parser: catches a refactor that moves/renames GENERATED_TOOLS.
        expect(generatedKinds.size).toBeGreaterThan(5)

        const missing = [...generatedKinds].filter((kind) => !(kind in QUERY_KIND_TO_PRODUCT_KEY))
        expect(missing).toEqual([])
    })
})
