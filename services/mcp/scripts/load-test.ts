#!/usr/bin/env npx tsx
/* eslint-disable no-console */

const BASE_URL = process.env.MCP_URL || 'https://mcp.us.posthog.com'
const API_KEY = process.env.MCP_API_KEY
if (!API_KEY) {
    console.error('MCP_API_KEY environment variable is required')
    process.exit(1)
}
const RPS = parseInt(process.env.RPS || '10', 10)
const DURATION_SECS = parseInt(process.env.DURATION || '30', 10)

interface ToolCall {
    name: string
    arguments: Record<string, unknown>
}

const TOOLS: ToolCall[] = [
    { name: 'user-get', arguments: { uuid: '@me' } },
    { name: 'project-get', arguments: { id: 2 } },
    { name: 'organization-get', arguments: {} },
    { name: 'feature-flag-get-all', arguments: { limit: 3 } },
    { name: 'feature-flag-get-all', arguments: { limit: 5, offset: 10 } },
    { name: 'feature-flag-get-all', arguments: { limit: 3, offset: 50 } },
    { name: 'feature-flag-get-definition', arguments: { id: 683820 } },
    { name: 'dashboards-get-all', arguments: { limit: 3 } },
    { name: 'dashboards-get-all', arguments: { limit: 5, search: 'revenue' } },
    { name: 'insights-list', arguments: { limit: 3 } },
    { name: 'insights-list', arguments: { limit: 5, search: 'funnel' } },
    { name: 'surveys-get-all', arguments: { limit: 3 } },
    { name: 'annotations-list', arguments: { limit: 3 } },
    { name: 'cohorts-list', arguments: { limit: 3 } },
    { name: 'roles-list', arguments: { limit: 3 } },
    { name: 'org-members-list', arguments: { limit: 3 } },
    { name: 'actions-get-all', arguments: { limit: 3 } },
    { name: 'experiment-list', arguments: { limit: 3 } },
    { name: 'batch-exports-list', arguments: { limit: 3 } },
    { name: 'integrations-list', arguments: { limit: 3 } },
    { name: 'alerts-list', arguments: { limit: 3 } },
    { name: 'notebooks-list', arguments: { limit: 3 } },
    { name: 'session-recording-playlists-list', arguments: { limit: 3 } },
    { name: 'cdp-functions-list', arguments: { limit: 3 } },
    { name: 'docs-search', arguments: { query: 'feature flags' } },
    { name: 'docs-search', arguments: { query: 'session replay' } },
    { name: 'persons-list', arguments: { limit: 3 } },
    { name: 'early-access-feature-list', arguments: { limit: 3 } },
    { name: 'view-list', arguments: { limit: 3 } },
    { name: 'workflows-list', arguments: { limit: 3 } },
]

function pick<T>(arr: T[]): T {
    return arr[Math.floor(Math.random() * arr.length)] as T
}

let nextId = 1

function makeJsonRpc(method: string, params: Record<string, unknown>): string {
    return JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params })
}

interface Stats {
    sent: number
    ok: number
    errors: number
    latencies: number[]
    errorDetails: Map<string, number>
}

const stats: Stats = {
    sent: 0,
    ok: 0,
    errors: 0,
    latencies: [],
    errorDetails: new Map(),
}

async function initSession(): Promise<string | null> {
    const body = makeJsonRpc('initialize', {
        protocolVersion: '2025-03-26',
        capabilities: {},
        clientInfo: { name: 'load-test', version: '1.0.0' },
    })

    const res = await fetch(`${BASE_URL}/mcp`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${API_KEY}`,
            Accept: 'application/json, text/event-stream',
        },
        body,
    })

    const sessionId = res.headers.get('mcp-session-id')
    // drain response
    await res.text()
    return sessionId
}

async function callTool(tool: ToolCall, sessionId: string): Promise<void> {
    const start = performance.now()
    stats.sent++

    try {
        const body = makeJsonRpc('tools/call', {
            name: tool.name,
            arguments: { ...tool.arguments, context: 'Load test' },
        })

        const res = await fetch(`${BASE_URL}/mcp`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${API_KEY}`,
                Accept: 'application/json, text/event-stream',
                'mcp-session-id': sessionId,
            },
            body,
            signal: AbortSignal.timeout(30_000),
        })

        const text = await res.text()
        const elapsed = performance.now() - start

        if (res.ok) {
            stats.ok++
            stats.latencies.push(elapsed)
        } else {
            stats.errors++
            const body = text.slice(0, 200)
            const key = `HTTP ${res.status}: ${body}`
            stats.errorDetails.set(key, (stats.errorDetails.get(key) || 0) + 1)
        }
    } catch (e: unknown) {
        stats.errors++
        const elapsed = performance.now() - start
        stats.latencies.push(elapsed)
        const key = e instanceof Error ? e.message.slice(0, 60) : 'unknown'
        stats.errorDetails.set(key, (stats.errorDetails.get(key) || 0) + 1)
    }
}

function percentile(sorted: number[], p: number): number {
    const idx = Math.ceil((p / 100) * sorted.length) - 1
    return sorted[Math.max(0, idx)] ?? 0
}

function printStats(): void {
    const sorted = [...stats.latencies].sort((a, b) => a - b)
    console.log(`\n\n=== Load Test Results ===`)
    console.log(`Total sent: ${stats.sent}`)
    console.log(`OK: ${stats.ok}`)
    console.log(`Errors: ${stats.errors}`)
    console.log(`Error rate: ${stats.sent ? ((stats.errors / stats.sent) * 100).toFixed(1) : 0}%`)

    if (sorted.length) {
        const avg = sorted.reduce((a, b) => a + b, 0) / sorted.length
        console.log(`\nLatency (ms):`)
        console.log(`  min: ${sorted[0]!.toFixed(0)}`)
        console.log(`  avg: ${avg.toFixed(0)}`)
        console.log(`  p50: ${percentile(sorted, 50).toFixed(0)}`)
        console.log(`  p95: ${percentile(sorted, 95).toFixed(0)}`)
        console.log(`  p99: ${percentile(sorted, 99).toFixed(0)}`)
        console.log(`  max: ${sorted[sorted.length - 1]!.toFixed(0)}`)
    }
    if (stats.errorDetails.size) {
        console.log(`\nError breakdown:`)
        for (const [k, v] of stats.errorDetails) {
            console.log(`  ${k}: ${v}`)
        }
    }
}

async function run(): Promise<void> {
    const sessionId = await initSession()
    if (!sessionId) {
        console.error('Failed to get session ID from initialize. Continuing without session.')
    } else {
    }

    const intervalMs = 1000 / RPS
    const endTime = Date.now() + DURATION_SECS * 1000
    let tick = 0

    const printInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - (endTime - DURATION_SECS * 1000)) / 1000)
        const inflight = stats.sent - stats.ok - stats.errors
        process.stdout.write(
            `\r[${elapsed}s] sent=${stats.sent} ok=${stats.ok} err=${stats.errors} inflight=${inflight}`
        )
    }, 500)

    while (Date.now() < endTime) {
        const tool = pick(TOOLS)
        callTool(tool, sessionId || '') // fire and forget
        tick++

        const nextFireAt = endTime - DURATION_SECS * 1000 + tick * intervalMs
        const sleepMs = nextFireAt - Date.now()
        if (sleepMs > 0) {
            await new Promise((r) => setTimeout(r, sleepMs))
        }
    }

    // wait for in-flight requests

    const deadline = Date.now() + 30_000
    while (stats.sent > stats.ok + stats.errors && Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 200))
    }

    clearInterval(printInterval)
    printStats()
}

run().catch((e) => {
    console.error(e)
    process.exit(1)
})
