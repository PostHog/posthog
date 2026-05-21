import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({
        capture: vi.fn(),
        shutdown: () => Promise.resolve(),
    }),
}))

vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn().mockResolvedValue(false),
    evaluateFeatureFlags: vi.fn().mockResolvedValue({}),
}))

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn().mockRejectedValue(new Error('mocked')),
    filterValidEntries: vi.fn().mockReturnValue([]),
    loadManifestFromArchive: vi.fn().mockReturnValue({ resources: [] }),
    clearResourceCache: vi.fn(),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn().mockResolvedValue([]),
}))

import type { RequestProperties } from '@/lib/request-properties'
import { McpDispatcher } from '@/hono/dispatcher'
import { ToolCatalog } from '@/hono/tool-catalog'

class MockRedis {
    private store = new Map<string, string>()
    async get(key: string): Promise<string | null> {
        return this.store.get(key) ?? null
    }
    async set(key: string, value: string): Promise<'OK'> {
        this.store.set(key, value)
        return 'OK'
    }
    async del(key: string): Promise<number> {
        return this.store.delete(key) ? 1 : 0
    }
    async expire(): Promise<number> {
        return 1
    }
    async ttl(): Promise<number> {
        return 3600
    }
}

const mockUserResponse = {
    uuid: 'test-uuid',
    distinct_id: 'test-distinct-id',
    first_name: 'Test',
    last_name: 'User',
    email: 'test@test.com',
}

const mockOrgsResponse = {
    results: [{ id: 'org-1', name: 'Test Org', slug: 'test' }],
}

const mockProjectsResponse = {
    results: [{ id: 1, uuid: 'proj-1', name: 'Test Project', organization: 'org-1' }],
}

let fetchCallCount = 0

function createMockFetch(): typeof fetch {
    return async (input: string | URL | Request): Promise<Response> => {
        fetchCallCount++
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
        const path = new URL(url).pathname

        let body: unknown = {}
        if (path.includes('/api/users/@me')) body = mockUserResponse
        else if (path.includes('/api/organizations')) body = mockOrgsResponse
        else if (path.includes('/api/projects') || path.includes('/api/environments')) body = mockProjectsResponse
        else if (path.includes('/decide')) body = { featureFlags: {} }

        return new Response(JSON.stringify(body), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        })
    }
}

const WARM_USER_HASH = 'warm-user-for-profiling'

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        userHash: WARM_USER_HASH,
        apiToken: 'phx_test_token',
        sessionId: 'sess-warm',
        mcpClientName: 'test-profiler',
        mcpClientVersion: '1.0.0',
        mcpProtocolVersion: '2025-03-26',
        transport: 'streamable-http',
        requestStartTime: Date.now(),
        ...overrides,
    }
}

function makeColdProps(): RequestProperties {
    return makeProps({
        userHash: `user-${Math.random().toString(36).slice(2, 10)}`,
        sessionId: `sess-${Math.random().toString(36).slice(2, 10)}`,
    })
}

function makeJsonRpcBody(method: string, params?: Record<string, unknown>): string {
    return JSON.stringify({
        jsonrpc: '2.0',
        id: Math.floor(Math.random() * 1_000_000),
        method,
        ...(params ? { params } : {}),
    })
}

function makeRequest(body: string): Request {
    return new Request('http://localhost/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
    })
}

function fmt(bytes: number): string {
    if (Math.abs(bytes) < 1024) return `${bytes} B`
    const kb = bytes / 1024
    if (Math.abs(kb) < 1024) return `${kb.toFixed(1)} KB`
    return `${(kb / 1024).toFixed(2)} MB`
}

function gc(): void {
    if (global.gc) {
        global.gc()
        global.gc()
    }
}

function percentile(sorted: number[], p: number): number {
    const idx = Math.ceil((p / 100) * sorted.length) - 1
    return sorted[Math.max(0, idx)]
}

function stats(timings: number[]): { min: number; p50: number; p95: number; p99: number; max: number; avg: number } {
    const sorted = [...timings].sort((a, b) => a - b)
    return {
        min: sorted[0],
        p50: percentile(sorted, 50),
        p95: percentile(sorted, 95),
        p99: percentile(sorted, 99),
        max: sorted[sorted.length - 1],
        avg: timings.reduce((a, b) => a + b, 0) / timings.length,
    }
}

const INIT_PARAMS = {
    protocolVersion: '2025-03-26',
    capabilities: {},
    clientInfo: { name: 'test', version: '1.0' },
}

describe('McpDispatcher profiling', () => {
    let dispatcher: McpDispatcher
    let catalog: ToolCatalog
    let originalFetch: typeof fetch

    beforeAll(async () => {
        originalFetch = globalThis.fetch
        globalThis.fetch = createMockFetch()

        process.env.POSTHOG_API_BASE_URL = 'http://localhost:19876'
        process.env.POSTHOG_ANALYTICS_API_KEY = 'phc_test'
        process.env.POSTHOG_ANALYTICS_HOST = 'http://localhost:19876'

        const redis = new MockRedis()
        catalog = new ToolCatalog()
        dispatcher = new McpDispatcher(catalog, redis as any)
        await dispatcher.warmup()

        // Prime the warm cache
        await dispatcher.handleRequest(
            makeRequest(makeJsonRpcBody('tools/list')),
            makeProps()
        )
    })

    afterAll(() => {
        globalThis.fetch = originalFetch
    })

    it('reports warmup stats', () => {
        const entries = catalog.getPreBuiltEntries()
        console.log(`\n  [warmup] ${entries.length} tools loaded`)
        expect(entries.length).toBeGreaterThan(0)
    })

    it('measures cold cache init latency', async () => {
        console.log('\n  --- Cold Cache Init Latency (first request per user, unique userHash) ---')

        const coldTimings: number[] = []
        const coldFetchCounts: number[] = []

        for (let i = 0; i < 20; i++) {
            const before = fetchCallCount
            const start = performance.now()
            const resp = await dispatcher.handleRequest(
                makeRequest(makeJsonRpcBody('initialize', INIT_PARAMS)),
                makeColdProps()
            )
            const ms = performance.now() - start
            const fetches = fetchCallCount - before

            coldTimings.push(ms)
            coldFetchCounts.push(fetches)
            expect(resp.status).toBe(200)
        }

        const s = stats(coldTimings)
        const avgFetches = coldFetchCounts.reduce((a, b) => a + b, 0) / coldFetchCounts.length
        console.log(`    20 cold inits:`)
        console.log(`      avg: ${s.avg.toFixed(2)}ms  p50: ${s.p50.toFixed(2)}ms  p95: ${s.p95.toFixed(2)}ms  p99: ${s.p99.toFixed(2)}ms`)
        console.log(`      min: ${s.min.toFixed(2)}ms  max: ${s.max.toFixed(2)}ms`)
        console.log(`      avg fetch calls per cold init: ${avgFetches.toFixed(1)}`)
    }, 30_000)

    it('measures warm cache request latency', async () => {
        console.log('\n  --- Warm Cache Request Latency (same userHash, cache populated) ---')

        for (const [label, method, params] of [
            ['initialize', 'initialize', INIT_PARAMS],
            ['tools/list', 'tools/list', undefined],
            ['tools/call', 'tools/call', { name: 'user-get', arguments: {} }],
            ['resources/list', 'resources/list', undefined],
            ['ping', 'ping', undefined],
        ] as const) {
            // JIT warmup
            for (let i = 0; i < 10; i++) {
                await dispatcher.handleRequest(
                    makeRequest(makeJsonRpcBody(method, params as Record<string, unknown> | undefined)),
                    makeProps()
                )
            }

            const timings: number[] = []
            for (let i = 0; i < 100; i++) {
                const start = performance.now()
                await dispatcher.handleRequest(
                    makeRequest(makeJsonRpcBody(method, params as Record<string, unknown> | undefined)),
                    makeProps()
                )
                timings.push(performance.now() - start)
            }

            const s = stats(timings)
            console.log(
                `    ${label.padEnd(16)}` +
                    `  avg: ${s.avg.toFixed(2).padStart(7)}ms` +
                    `  p50: ${s.p50.toFixed(2).padStart(7)}ms` +
                    `  p95: ${s.p95.toFixed(2).padStart(7)}ms` +
                    `  p99: ${s.p99.toFixed(2).padStart(7)}ms`
            )
        }
    }, 120_000)

    it('measures cold vs warm fetch overhead', async () => {
        console.log('\n  --- Cold vs Warm: Fetch Call Counts ---')

        // Cold: new userHash
        const coldBefore = fetchCallCount
        await dispatcher.handleRequest(
            makeRequest(makeJsonRpcBody('tools/call', { name: 'user-get', arguments: {} })),
            makeColdProps()
        )
        const coldFetches = fetchCallCount - coldBefore

        // Warm: reused userHash (cache hit)
        const warmBefore = fetchCallCount
        await dispatcher.handleRequest(
            makeRequest(makeJsonRpcBody('tools/call', { name: 'user-get', arguments: {} })),
            makeProps()
        )
        const warmFetches = fetchCallCount - warmBefore

        console.log(`    Cold request fetch calls: ${coldFetches}`)
        console.log(`    Warm request fetch calls: ${warmFetches}`)
        console.log(`    Savings from cache:       ${coldFetches - warmFetches} fewer API calls`)
    }, 15_000)

    it('measures per-request memory (cold cache)', async () => {
        console.log('\n  --- Per-Request Memory: Cold Cache ---')
        for (const N of [1, 10, 50]) {
            gc()
            await new Promise((r) => setTimeout(r, 30))
            gc()

            const before = process.memoryUsage().heapUsed
            const start = performance.now()

            for (let i = 0; i < N; i++) {
                await dispatcher.handleRequest(
                    makeRequest(makeJsonRpcBody('tools/call', { name: 'user-get', arguments: {} })),
                    makeColdProps()
                )
            }

            const elapsed = performance.now() - start
            gc()
            const after = process.memoryUsage().heapUsed
            const delta = after - before

            console.log(
                `    ${String(N).padStart(3)} reqs:` +
                    `  ${fmt(delta).padStart(12)} heap (${fmt(delta / N).padStart(10)}/req),` +
                    `  ${elapsed.toFixed(0)}ms (${(elapsed / N).toFixed(1)}ms/req)`
            )
        }
    }, 120_000)

    it('measures concurrent burst (warm cache)', async () => {
        console.log('\n  --- Concurrent Burst: Warm Cache ---')

        for (const burst of [10, 50, 100, 200]) {
            gc()
            await new Promise((r) => setTimeout(r, 50))
            gc()
            const before = process.memoryUsage().heapUsed
            const burstStart = performance.now()

            const results = await Promise.all(
                Array.from({ length: burst }, () =>
                    dispatcher.handleRequest(
                        makeRequest(makeJsonRpcBody('tools/call', { name: 'user-get', arguments: {} })),
                        makeProps()
                    )
                )
            )

            const burstMs = performance.now() - burstStart
            gc()
            const after = process.memoryUsage().heapUsed
            const delta = after - before

            console.log(
                `    ${String(burst).padStart(3)} concurrent:` +
                    `  ${burstMs.toFixed(0).padStart(5)}ms total,` +
                    `  ${(burstMs / burst).toFixed(2)}ms/req,` +
                    `  ${fmt(delta).padStart(10)} heap (${fmt(delta / burst)}/req)`
            )

            for (const r of results) {
                expect(r.status).toBe(200)
            }
        }
    }, 60_000)

    it('measures concurrent burst (cold cache)', async () => {
        console.log('\n  --- Concurrent Burst: Cold Cache ---')

        for (const burst of [10, 50, 100]) {
            gc()
            await new Promise((r) => setTimeout(r, 50))
            gc()
            const before = process.memoryUsage().heapUsed
            const burstStart = performance.now()

            const results = await Promise.all(
                Array.from({ length: burst }, () =>
                    dispatcher.handleRequest(
                        makeRequest(makeJsonRpcBody('tools/call', { name: 'user-get', arguments: {} })),
                        makeColdProps()
                    )
                )
            )

            const burstMs = performance.now() - burstStart
            gc()
            const after = process.memoryUsage().heapUsed
            const delta = after - before

            console.log(
                `    ${String(burst).padStart(3)} concurrent:` +
                    `  ${burstMs.toFixed(0).padStart(5)}ms total,` +
                    `  ${(burstMs / burst).toFixed(2)}ms/req,` +
                    `  ${fmt(delta).padStart(10)} heap (${fmt(delta / burst)}/req)`
            )

            for (const r of results) {
                expect(r.status).toBe(200)
            }
        }
    }, 60_000)

    it('measures batch JSON-RPC', async () => {
        console.log('\n  --- Batch JSON-RPC ---')

        for (const batchSize of [5, 20, 50]) {
            gc()
            await new Promise((r) => setTimeout(r, 50))
            gc()

            const before = process.memoryUsage().heapUsed
            const batchStart = performance.now()

            const batch = Array.from({ length: batchSize }, (_, i) => ({
                jsonrpc: '2.0' as const,
                id: i + 1,
                method: i === 0 ? 'initialize' : i === 1 ? 'tools/list' : 'tools/call',
                params:
                    i === 0
                        ? INIT_PARAMS
                        : i === 1
                          ? {}
                          : { name: 'user-get', arguments: {} },
            }))

            const resp = await dispatcher.handleRequest(
                new Request('http://localhost/mcp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(batch),
                }),
                makeProps()
            )

            const results = (await resp.json()) as unknown[]
            const batchMs = performance.now() - batchStart

            gc()
            const after = process.memoryUsage().heapUsed
            const delta = after - before

            console.log(
                `    batch of ${String(batchSize).padStart(2)}:` +
                    `  ${batchMs.toFixed(0).padStart(5)}ms,` +
                    `  ${results.length} responses,` +
                    `  ${fmt(delta).padStart(10)} heap`
            )

            expect(results.length).toBe(batchSize)
        }
    }, 60_000)

    it('reports final memory', () => {
        gc()
        const m = process.memoryUsage()
        console.log('\n  --- Final Memory ---')
        console.log(`    Heap used:  ${fmt(m.heapUsed)}`)
        console.log(`    Heap total: ${fmt(m.heapTotal)}`)
        console.log(`    RSS:        ${fmt(m.rss)}`)
        console.log(`    External:   ${fmt(m.external)}`)
    })
})
