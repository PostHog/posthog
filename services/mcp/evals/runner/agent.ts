/**
 * Agent-mode runner — replays each benchmark intent through a real agent loop
 * against a LIVE MCP server, records which tools the agent reached for, and
 * scores tool selection against the fixtures' expected/acceptable paths.
 *
 * Probe mode (`probe.ts`) answers "does this tool work?". This answers "does an
 * agent pick this tool when it should?" — the question a tool description,
 * schema, or name change actually moves.
 *
 * Writes are stubbed by default: the agent is told the call was accepted, and
 * nothing is mutated. Tool *selection* is still recorded, which is what we
 * score. Pass --allow-writes to execute them for real (only against a scratch
 * project).
 *
 * Usage:
 *   ANTHROPIC_API_KEY=... LIVE_MCP_URL=http://localhost:9876 LIVE_MCP_TOKEN=phx_... \
 *     pnpm exec tsx evals/runner/agent.ts [--out score.json] [--max-steps 12] [--allow-writes]
 *
 * Exit code is non-zero only when the run could not complete — comparing scores
 * across two runs is the caller's job, not a threshold baked in here.
 */

import Anthropic from '@anthropic-ai/sdk'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { writeFileSync } from 'node:fs'
import process from 'node:process'

import { loadBenchmark, type BenchmarkTask } from '../benchmark/schema'
import { formatSelectionSummary, scoreTask, summarizeSelection, type TaskSelection } from './selection'

const DEFAULT_MODEL = 'claude-opus-4-8'
const DEFAULT_MAX_STEPS = 12
const MAX_TOKENS = 16_000

/**
 * Deliberately neutral: it says what the agent is and what to do, and nothing
 * about which tool to prefer. Any nudge here ("prefer typed queries over SQL")
 * would make the benchmark measure this prompt instead of the tool catalog the
 * benchmark exists to measure.
 */
const SYSTEM_PROMPT = [
    'You are an analytics agent working in a PostHog project via MCP tools.',
    "Use the available tools to answer the user's request, then give a short answer.",
    'If a tool call fails, read the error and adapt.',
].join(' ')

interface AdvertisedTool {
    name: string
    description?: string
    inputSchema?: unknown
    annotations?: { readOnlyHint?: boolean }
}

export interface AgentTaskRun {
    task_id: string
    /** Names of calls that returned without an error, in order — what gets scored. */
    calls: string[]
    /** Calls the server rejected. Surfaced so a server fault isn't read as a bad pick. */
    errored: string[]
    /** Write calls that were recorded but not executed (dry run). */
    stubbed: string[]
    steps: number
    stop_reason: string | null
    /** Set when the loop could not run the task at all. */
    error?: string
}

function toAnthropicTools(advertised: AdvertisedTool[]): Anthropic.ToolUnion[] {
    return advertised.map((tool) => ({
        name: tool.name,
        description: tool.description ?? '',
        // MCP advertises a JSON Schema, which is exactly what the Messages API
        // wants — pass it through rather than re-deriving a lossy copy.
        input_schema: (tool.inputSchema ?? { type: 'object', properties: {} }) as Anthropic.Tool.InputSchema,
    }))
}

/** Flatten an MCP tool result into the text the model sees as its tool_result. */
function resultToText(content: unknown): string {
    if (!Array.isArray(content)) {
        return JSON.stringify(content ?? null)
    }
    const text = content
        .map((item) => (item && typeof item === 'object' && 'text' in item ? String(item.text) : ''))
        .filter(Boolean)
        .join('\n')
    return text || JSON.stringify(content)
}

async function runTask(
    anthropic: Anthropic,
    mcp: Client,
    task: BenchmarkTask,
    options: {
        tools: Anthropic.ToolUnion[]
        advertised: Map<string, AdvertisedTool>
        model: string
        maxSteps: number
        allowWrites: boolean
    }
): Promise<AgentTaskRun> {
    const run: AgentTaskRun = { task_id: task.id, calls: [], errored: [], stubbed: [], steps: 0, stop_reason: null }
    const messages: Anthropic.MessageParam[] = [{ role: 'user', content: task.intent }]

    while (run.steps < options.maxSteps) {
        run.steps += 1
        let response: Anthropic.Message
        try {
            response = await anthropic.messages.create({
                model: options.model,
                max_tokens: MAX_TOKENS,
                thinking: { type: 'adaptive' },
                system: SYSTEM_PROMPT,
                tools: options.tools,
                messages,
            })
        } catch (error) {
            run.error = error instanceof Error ? error.message : String(error)
            return run
        }

        run.stop_reason = response.stop_reason ?? null
        // Append the whole content, not just text: thinking and tool_use blocks
        // must survive the round trip or the next request is rejected.
        messages.push({ role: 'assistant', content: response.content })

        if (response.stop_reason === 'refusal' || response.stop_reason === 'end_turn') {
            return run
        }
        if (response.stop_reason === 'pause_turn') {
            // A server-side tool hit its iteration cap; re-send to resume.
            continue
        }

        const toolUses = response.content.filter((block): block is Anthropic.ToolUseBlock => block.type === 'tool_use')
        if (toolUses.length === 0) {
            return run
        }

        const results: Anthropic.ToolResultBlockParam[] = []
        for (const call of toolUses) {
            results.push(await executeCall(mcp, call, run, options))
        }
        messages.push({ role: 'user', content: results })
    }

    return run
}

async function executeCall(
    mcp: Client,
    call: Anthropic.ToolUseBlock,
    run: AgentTaskRun,
    options: { advertised: Map<string, AdvertisedTool>; allowWrites: boolean }
): Promise<Anthropic.ToolResultBlockParam> {
    const readOnly = options.advertised.get(call.name)?.annotations?.readOnlyHint === true
    if (!readOnly && !options.allowWrites) {
        // The agent picked a write tool: that choice is the thing being scored,
        // so record it and answer honestly rather than mutating the project.
        run.calls.push(call.name)
        run.stubbed.push(call.name)
        return {
            type: 'tool_result',
            tool_use_id: call.id,
            content: `Accepted. This eval runs in dry-run mode, so ${call.name} was not executed and no data changed.`,
        }
    }

    try {
        const result = await mcp.callTool({ name: call.name, arguments: (call.input ?? {}) as Record<string, unknown> })
        const text = resultToText(result.content)
        if (result.isError) {
            run.errored.push(call.name)
            return { type: 'tool_result', tool_use_id: call.id, content: text, is_error: true }
        }
        run.calls.push(call.name)
        return { type: 'tool_result', tool_use_id: call.id, content: text }
    } catch (error) {
        run.errored.push(call.name)
        return {
            type: 'tool_result',
            tool_use_id: call.id,
            content: error instanceof Error ? error.message : String(error),
            is_error: true,
        }
    }
}

function numericFlag(name: string, fallback: number): number {
    const index = process.argv.indexOf(name)
    if (index === -1) {
        return fallback
    }
    const parsed = Number(process.argv[index + 1])
    if (!Number.isInteger(parsed) || parsed <= 0) {
        console.error(`${name} requires a positive integer`)
        process.exit(2)
    }
    return parsed
}

async function main(): Promise<void> {
    const url = process.env.LIVE_MCP_URL ?? 'http://localhost:9876'
    const token = process.env.LIVE_MCP_TOKEN
    if (!token) {
        console.error('LIVE_MCP_TOKEN is required (a personal API key for the target instance)')
        process.exit(2)
    }
    if (!process.env.ANTHROPIC_API_KEY) {
        console.error('ANTHROPIC_API_KEY is required to drive the agent loop')
        process.exit(2)
    }

    const outFlagIndex = process.argv.indexOf('--out')
    const outPath = outFlagIndex === -1 ? null : (process.argv[outFlagIndex + 1] ?? null)
    if (outFlagIndex !== -1 && outPath === null) {
        console.error('--out requires a file path')
        process.exit(2)
    }
    const maxSteps = numericFlag('--max-steps', DEFAULT_MAX_STEPS)
    const allowWrites = process.argv.includes('--allow-writes')
    const model = process.env.EVAL_MODEL ?? DEFAULT_MODEL

    const benchmark = loadBenchmark()
    const transport = new StreamableHTTPClientTransport(new URL('/mcp', url), {
        // Pin tools mode: agent mode scores the per-tool roster, and the server's
        // auto-detection would otherwise resolve this client to the single-exec
        // CLI default — which has no per-tool choice to score.
        requestInit: { headers: { Authorization: `Bearer ${token}`, 'x-posthog-mcp-mode': 'tools' } },
    })
    const mcp = new Client({ name: 'mcp-eval-agent', version: '0.0.0' }, { capabilities: {} })
    await mcp.connect(transport)

    try {
        const listed = await mcp.listTools()
        const advertised = new Map<string, AdvertisedTool>(
            listed.tools.map((tool) => [tool.name, tool as AdvertisedTool])
        )
        const tools = toAnthropicTools([...advertised.values()])
        const anthropic = new Anthropic()

        process.stdout.write(
            `agent mode: ${benchmark.tasks.length} tasks, ${tools.length} tools, model ${model}` +
                `${allowWrites ? ', WRITES ENABLED' : ', writes stubbed'}\n`
        )

        const runs: AgentTaskRun[] = []
        const scored: TaskSelection[] = []
        for (const task of benchmark.tasks) {
            const run = await runTask(anthropic, mcp, task, { tools, advertised, model, maxSteps, allowWrites })
            runs.push(run)
            scored.push(scoreTask(task, run.calls))
            process.stdout.write(`  ${task.id}: ${run.calls.join(' → ') || '(no calls)'}\n`)
        }

        const summary = summarizeSelection(scored)
        process.stdout.write(formatSelectionSummary(summary) + '\n')

        // A typed tool that errored can look like a bad pick, so name those runs
        // rather than letting a server fault land on the model's score.
        const faults = runs.filter((run) => run.errored.length > 0 || run.error)
        for (const run of faults) {
            process.stdout.write(
                `  NOTE ${run.task_id}: ${run.error ?? `tool errors from ${[...new Set(run.errored)].join(', ')}`}\n`
            )
        }

        if (outPath) {
            writeFileSync(
                outPath,
                JSON.stringify({ benchmark_version: benchmark.version, model, summary, runs }, null, 2)
            )
            process.stdout.write(`wrote ${outPath}\n`)
        }
        process.exit(summary.tasks_scored === 0 ? 1 : 0)
    } finally {
        await mcp.close().catch(() => undefined)
    }
}

void main()
