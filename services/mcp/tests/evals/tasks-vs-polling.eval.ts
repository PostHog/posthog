import Anthropic from '@anthropic-ai/sdk'
import { setupServer } from 'msw/node'
import { writeFileSync } from 'node:fs'
import { afterAll, beforeAll, describe, it } from 'vitest'

import { createApp } from '@/hono/app'
import { TASKS_EXTENSION_ID } from '@/hono/mcp-tasks'

import { createInMemoryRedis } from '../hono/helpers/in-memory-redis'
import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { FRESH_CONVERSION_CHANCE, RecalculationBackend, STALE_CONVERSION_CHANCE } from './recalculation-backend'

// Runs one agent task against the in-process MCP server twice: once as a client without the
// Tasks extension, where the model has to poll the status tool, and once as a client that
// declares it, where the client polls `tasks/get` and the model gets one finished result.
// Everything else is the same: model, prompt, tools, and the simulated job.
//
//   ANTHROPIC_API_KEY=... pnpm --filter=@posthog/mcp run eval:tasks
//
// Knobs: EVAL_MODEL, EVAL_EFFORT, EVAL_TRIALS, EVAL_JOB_SECONDS, EVAL_ARMS, EVAL_CONCURRENCY, EVAL_OUT.

type Arm = 'polling' | 'polling-no-wait' | 'tasks'

const MODEL = process.env.EVAL_MODEL ?? 'claude-opus-5-5'
const EFFORT = (process.env.EVAL_EFFORT ?? 'medium') as 'low' | 'medium' | 'high'
const TRIALS = Number(process.env.EVAL_TRIALS ?? 3)
const JOB_MS = Number(process.env.EVAL_JOB_SECONDS ?? 60) * 1000
const ARMS = (process.env.EVAL_ARMS ?? 'polling,tasks').split(',') as Arm[]
const CONCURRENCY = Number(process.env.EVAL_CONCURRENCY ?? 4)
const MAX_TURNS = 40
const TOKEN = 'phx_tasks_eval_token'

const EVAL_TOOLS = [
    'experiment-get',
    'experiment-metrics-recalculation-create',
    'experiment-metrics-recalculation-retrieve',
    'experiment-metrics-recalculation-latest-retrieve',
]
const STATUS_TOOLS = new Set([
    'experiment-metrics-recalculation-retrieve',
    'experiment-metrics-recalculation-latest-retrieve',
])

// USD per million tokens. Cache writes cost 1.25x the input rate.
const PRICES: Record<string, { input: number; cacheRead: number; output: number }> = {
    'claude-opus-5-5': { input: 4, cacheRead: 0.2, output: 20 },
    'claude-sonnet-5-5': { input: 2, cacheRead: 0.2, output: 10 },
}

const SYSTEM_PROMPT = `You are an analytics assistant with access to the user's PostHog project through tools.
Answer the user's question with data from the tools. Be concise in the final answer.`

const WAIT_TOOL: Anthropic.Beta.BetaTool = {
    name: 'wait',
    description: 'Pause for a number of seconds before you continue. Use it while a background job runs.',
    input_schema: {
        type: 'object',
        properties: { seconds: { type: 'integer', minimum: 1, maximum: 60 } },
        required: ['seconds'],
    },
}

interface CaseResult {
    arm: Arm
    trial: number
    experimentId: number
    outcome: 'fresh' | 'stale' | 'incomplete'
    modelTurns: number
    inputTokens: number
    cacheWriteTokens: number
    cacheReadTokens: number
    outputTokens: number
    costUsd: number
    mcpToolCalls: number
    statusToolCalls: number
    waitCalls: number
    waitSeconds: number
    clientTaskPolls: number
    backendStatusReads: number
    wallSeconds: number
    fallbackUsed: boolean
    toolSequence: string[]
    finalAnswer: string
}

let app: ReturnType<typeof createApp>['app']
const backend = new RecalculationBackend(JOB_MS)
const mswServer = setupServer(...backend.handlers(), ...handlers, contextMillHandler)
const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

async function rpc(method: string, params: Record<string, unknown>, declareTasks: boolean): Promise<any> {
    const response = await app.request(`/mcp?tools=${EVAL_TOOLS.join(',')}`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'x-posthog-mcp-mode': 'tools',
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': method,
            ...(typeof params.name === 'string' ? { 'Mcp-Name': params.name } : {}),
        },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method,
            params: {
                ...params,
                _meta: {
                    'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                    'io.modelcontextprotocol/clientInfo': { name: 'tasks-eval', version: '0.0.1' },
                    'io.modelcontextprotocol/clientCapabilities': declareTasks
                        ? { extensions: { [TASKS_EXTENSION_ID]: {} } }
                        : {},
                },
            },
        }),
    })
    const json = (await response.json()) as { result?: any; error?: { message: string } }
    if (json.error) {
        throw new Error(`${method} failed: ${json.error.message}`)
    }
    return json.result
}

async function listTools(): Promise<Anthropic.Beta.BetaTool[]> {
    const { tools } = await rpc('tools/list', {}, false)
    return (tools as { name: string; description?: string; inputSchema: Record<string, unknown> }[]).map(
        ({ name, description, inputSchema }) => {
            const { $schema: _ignored, ...schema } = inputSchema
            return { name, description, input_schema: schema as Anthropic.Beta.BetaTool.InputSchema }
        }
    )
}

async function awaitTask(task: any, onPoll: () => void): Promise<any> {
    let current = task
    while (current.status === 'working' || current.status === 'input_required') {
        await sleep(current.pollIntervalMs ?? 5000)
        onPoll()
        current = await rpc('tasks/get', { taskId: task.taskId }, true)
    }
    if (current.status === 'completed') {
        return current.result
    }
    return { content: [{ type: 'text', text: `Task ${current.status}` }], isError: true }
}

function toolResultText(result: any): string {
    const blocks = Array.isArray(result?.content) ? result.content : []
    return blocks
        .filter((block: { type?: string }) => block.type === 'text')
        .map((block: { text: string }) => block.text)
        .join('\n')
}

function scoreAnswer(answer: string): CaseResult['outcome'] {
    const fresh = new RegExp(
        `${(FRESH_CONVERSION_CHANCE * 100).toFixed(1).replace('.', '\\.')}|${String(FRESH_CONVERSION_CHANCE).replace('.', '\\.')}|\\b95\\s*%`
    )
    const stale = new RegExp(
        `\\b${STALE_CONVERSION_CHANCE * 100}(\\.\\d+)?\\s*%|${String(STALE_CONVERSION_CHANCE).replace('.', '\\.')}\\b`
    )
    if (fresh.test(answer)) {
        return 'fresh'
    }
    return stale.test(answer) ? 'stale' : 'incomplete'
}

async function runCase(
    client: Anthropic,
    mcpTools: Anthropic.Beta.BetaTool[],
    arm: Arm,
    trial: number,
    experimentId: number
): Promise<CaseResult> {
    const declareTasks = arm === 'tasks'
    const tools = arm === 'polling-no-wait' ? mcpTools : [...mcpTools, WAIT_TOOL]
    const messages: Anthropic.Beta.BetaMessageParam[] = [
        {
            role: 'user',
            content: `The results on experiment ${experimentId} look stale to me. Get fresh numbers and tell me the test variant's chance to beat control on checkout conversion.`,
        },
    ]
    const result: CaseResult = {
        arm,
        trial,
        experimentId,
        outcome: 'incomplete',
        modelTurns: 0,
        inputTokens: 0,
        cacheWriteTokens: 0,
        cacheReadTokens: 0,
        outputTokens: 0,
        costUsd: 0,
        mcpToolCalls: 0,
        statusToolCalls: 0,
        waitCalls: 0,
        waitSeconds: 0,
        clientTaskPolls: 0,
        backendStatusReads: 0,
        wallSeconds: 0,
        fallbackUsed: false,
        toolSequence: [],
        finalAnswer: '',
    }
    const started = Date.now()

    for (let turn = 0; turn < MAX_TURNS; turn++) {
        const params: Anthropic.Beta.MessageCreateParamsNonStreaming = {
            model: MODEL,
            max_tokens: 16000,
            betas: ['server-side-fallback-2026-07-01'],
            cache_control: { type: 'ephemeral' },
            output_config: { effort: EFFORT },
            system: SYSTEM_PROMPT,
            tools,
            messages,
        }
        // This SDK's request types only know the array form of `fallbacks`, not the scalar `'default'`.
        const response = await client.beta.messages.create({
            ...params,
            fallbacks: 'default',
        } as unknown as typeof params)
        result.modelTurns += 1
        const usage = response.usage as Anthropic.Beta.BetaUsage & { iterations?: { type: string }[] }
        result.inputTokens += usage.input_tokens
        result.cacheWriteTokens += usage.cache_creation_input_tokens ?? 0
        result.cacheReadTokens += usage.cache_read_input_tokens ?? 0
        result.outputTokens += usage.output_tokens
        result.fallbackUsed ||= (usage.iterations ?? []).some((entry) => entry.type === 'fallback_message')

        // Append the whole content, thinking blocks included, so the history stays append-only.
        messages.push({ role: 'assistant', content: response.content })
        const toolUses = response.content.filter(
            (block): block is Anthropic.Beta.BetaToolUseBlock => block.type === 'tool_use'
        )
        if (response.stop_reason !== 'tool_use' || toolUses.length === 0) {
            result.finalAnswer = response.content
                .filter((block): block is Anthropic.Beta.BetaTextBlock => block.type === 'text')
                .map((block) => block.text)
                .join('\n')
            break
        }

        const toolResults: Anthropic.Beta.BetaToolResultBlockParam[] = []
        for (const toolUse of toolUses) {
            result.toolSequence.push(toolUse.name)
            if (toolUse.name === WAIT_TOOL.name) {
                const seconds = Math.min(Math.max(Number((toolUse.input as { seconds?: number }).seconds) || 1, 1), 60)
                result.waitCalls += 1
                result.waitSeconds += seconds
                await sleep(seconds * 1000)
                toolResults.push({
                    type: 'tool_result',
                    tool_use_id: toolUse.id,
                    content: `Waited ${seconds} seconds.`,
                })
                continue
            }
            result.mcpToolCalls += 1
            if (STATUS_TOOLS.has(toolUse.name)) {
                result.statusToolCalls += 1
            }
            let callResult = await rpc(
                'tools/call',
                { name: toolUse.name, arguments: toolUse.input as Record<string, unknown> },
                declareTasks
            )
            if (callResult.resultType === 'task') {
                callResult = await awaitTask(callResult, () => {
                    result.clientTaskPolls += 1
                })
            }
            toolResults.push({
                type: 'tool_result',
                tool_use_id: toolUse.id,
                content: toolResultText(callResult) || '(empty result)',
                is_error: callResult.isError === true,
            })
        }
        messages.push({ role: 'user', content: toolResults })
    }

    const price = PRICES[MODEL] ?? PRICES['claude-opus-5-5']!
    result.costUsd =
        (result.inputTokens * price.input +
            result.cacheWriteTokens * price.input * 1.25 +
            result.cacheReadTokens * price.cacheRead +
            result.outputTokens * price.output) /
        1_000_000
    result.wallSeconds = Math.round((Date.now() - started) / 1000)
    result.backendStatusReads = backend.countersFor(experimentId).statusReads
    result.outcome = scoreAnswer(result.finalAnswer)
    return result
}

async function runAll<T>(jobs: (() => Promise<T>)[], limit: number): Promise<T[]> {
    const results: T[] = new Array(jobs.length)
    let next = 0
    async function worker(): Promise<void> {
        while (next < jobs.length) {
            const index = next++
            results[index] = await jobs[index]!()
        }
    }
    await Promise.all(Array.from({ length: Math.min(limit, jobs.length) }, worker))
    return results
}

const mean = (values: number[]): number => values.reduce((sum, value) => sum + value, 0) / (values.length || 1)

function summarize(results: CaseResult[]): string {
    const rows = ARMS.map((arm) => {
        const cases = results.filter((r) => r.arm === arm)
        const fresh = cases.filter((r) => r.outcome === 'fresh').length
        const stat = (pick: (r: CaseResult) => number, digits = 1): string => mean(cases.map(pick)).toFixed(digits)
        return [
            arm,
            `${fresh}/${cases.length}`,
            stat((r) => r.modelTurns),
            stat((r) => r.mcpToolCalls),
            stat((r) => r.statusToolCalls),
            stat((r) => r.waitCalls),
            stat((r) => r.inputTokens + r.cacheWriteTokens + r.cacheReadTokens, 0),
            stat((r) => r.outputTokens, 0),
            `$${stat((r) => r.costUsd, 3)}`,
            stat((r) => r.wallSeconds, 0),
        ]
    })
    const header = [
        'arm',
        'fresh answer',
        'model turns',
        'MCP calls',
        'status polls by model',
        'wait calls',
        'input tokens',
        'output tokens',
        'cost',
        'wall s',
    ]
    return [header, header.map(() => '---'), ...rows].map((row) => `| ${row.join(' | ')} |`).join('\n')
}

describe('MCP Tasks extension vs model polling', () => {
    beforeAll(async () => {
        process.env.TEST = '1'
        process.env.MCP_TASKS_EXTENSION = 'true'
        mswServer.listen({ onUnhandledRequest: 'bypass' })
        const created = createApp(createInMemoryRedis())
        app = created.app
        await created.warmup()
    })

    afterAll(() => {
        mswServer.close()
    })

    it('compares model turns, tokens and time for one recalculation', async () => {
        const client = new Anthropic()
        const mcpTools = await listTools()
        const jobs = ARMS.flatMap((arm, armIndex) =>
            Array.from({ length: TRIALS }, (_, trial) => {
                const experimentId = 100 + armIndex * 100 + trial
                return () => runCase(client, mcpTools, arm, trial, experimentId)
            })
        )
        const results = await runAll(jobs, CONCURRENCY)

        const summary = `model ${MODEL}, effort ${EFFORT}, job ${JOB_MS / 1000}s, ${TRIALS} trials per arm\n\n${summarize(results)}`
        console.info(`\n${summary}\n`)
        if (process.env.EVAL_OUT) {
            writeFileSync(
                process.env.EVAL_OUT,
                JSON.stringify({ model: MODEL, effort: EFFORT, jobMs: JOB_MS, summary, results }, null, 2)
            )
        }
    })
})
