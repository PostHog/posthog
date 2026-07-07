/**
 * Deterministic probe runner — no LLM. Connects to a LIVE MCP server,
 * verifies every tool the benchmark references is advertised, executes each
 * task's read-only probe call, and prints/writes a score summary.
 *
 * Usage:
 *   LIVE_MCP_URL=http://localhost:9876 LIVE_MCP_TOKEN=phx_... \
 *     pnpm exec tsx evals/runner/probe.ts [--out score.json]
 *
 * Exit code is non-zero when any referenced tool is missing or any probe
 * fails, so the campaign (or CI) can gate on it directly.
 */

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js'
import { writeFileSync } from 'node:fs'
import process from 'node:process'

import { loadBenchmark, referencedTools, type BenchmarkTask } from '../benchmark/schema'
import { formatSummary, summarize, type ProbeResult, type ToolMiss } from './results'

interface AdvertisedTool {
    name: string
    annotations?: { readOnlyHint?: boolean }
}

async function runProbe(
    client: Client,
    task: BenchmarkTask,
    advertised: Map<string, AdvertisedTool>
): Promise<ProbeResult> {
    const probe = task.probe!
    const base = { task_id: task.id, tool: probe.tool }
    const tool = advertised.get(probe.tool)
    if (!tool) {
        return { ...base, status: 'skipped_not_advertised' }
    }
    // Enforce read-only from the LIVE advertisement, not just the fixture —
    // an annotation regression must fail the probe rather than mutate data.
    if (tool.annotations?.readOnlyHint !== true) {
        return { ...base, status: 'refused_not_read_only' }
    }

    const startedAt = Date.now()
    try {
        const result = await client.callTool({ name: probe.tool, arguments: probe.args }, undefined, {
            timeout: probe.max_ms,
        })
        const latency = Date.now() - startedAt
        if (result.isError) {
            const content = Array.isArray(result.content) ? result.content : []
            const text = content
                .map((item) => (item && typeof item === 'object' && 'text' in item ? String(item.text) : ''))
                .join(' ')
            return { ...base, status: 'tool_error', latency_ms: latency, error_snippet: text.slice(0, 200) }
        }
        return { ...base, status: 'ok', latency_ms: latency }
    } catch (error) {
        const latency = Date.now() - startedAt
        const message = error instanceof Error ? error.message : String(error)
        // The SDK raises a typed timeout when RequestOptions.timeout elapses —
        // classify on that, not on wall-clock heuristics.
        const isTimeout = error instanceof McpError && error.code === ErrorCode.RequestTimeout
        return {
            ...base,
            status: isTimeout ? 'timeout' : 'transport_error',
            latency_ms: latency,
            error_snippet: message.slice(0, 200),
        }
    }
}

async function main(): Promise<void> {
    const url = process.env.LIVE_MCP_URL ?? 'http://localhost:9876'
    const token = process.env.LIVE_MCP_TOKEN
    if (!token) {
        console.error('LIVE_MCP_TOKEN is required (a personal API key for the target instance)')
        process.exit(2)
    }
    const outFlagIndex = process.argv.indexOf('--out')
    const outPath = outFlagIndex === -1 ? null : (process.argv[outFlagIndex + 1] ?? null)
    if (outFlagIndex !== -1 && outPath === null) {
        console.error('--out requires a file path')
        process.exit(2)
    }

    const benchmark = loadBenchmark()
    const transport = new StreamableHTTPClientTransport(new URL('/mcp', url), {
        requestInit: { headers: { Authorization: `Bearer ${token}` } },
    })
    const client = new Client({ name: 'mcp-eval-probe', version: '0.0.0' }, { capabilities: {} })
    await client.connect(transport)

    try {
        const listed = await client.listTools()
        const advertised = new Map<string, AdvertisedTool>(
            listed.tools.map((tool) => [tool.name, tool as AdvertisedTool])
        )

        const toolMisses: ToolMiss[] = benchmark.tasks.flatMap((task) =>
            referencedTools(task)
                .filter((tool) => !advertised.has(tool))
                .map((tool) => ({ task_id: task.id, tool }))
        )

        const probes: ProbeResult[] = []
        for (const task of benchmark.tasks.filter((candidate) => candidate.probe)) {
            probes.push(await runProbe(client, task, advertised))
        }

        const summary = summarize({
            benchmarkVersion: benchmark.version,
            tasksTotal: benchmark.tasks.length,
            toolsReferenced: new Set(benchmark.tasks.flatMap(referencedTools)).size,
            toolMisses,
            probes,
        })

        // stdout directly: the summary IS the program output (oxlint strips console.log).
        process.stdout.write(formatSummary(summary) + '\n')
        if (outPath) {
            writeFileSync(outPath, JSON.stringify(summary, null, 2))
            process.stdout.write(`wrote ${outPath}\n`)
        }
        process.exit(summary.tool_misses.length > 0 || summary.probes_failed > 0 ? 1 : 0)
    } finally {
        await client.close().catch(() => undefined)
    }
}

void main()
