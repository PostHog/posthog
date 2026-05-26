import { post, send, type RunOptions } from './clients'
/**
 * `chatFlow` — multi-turn chat against an app, wired to the harness. Glues
 * `POST /run` (or its continuation via `POST /send/:id`) to a "wait for the
 * next assistant message" poller backed by ClickHouse `log_entries` —
 * which the runner publishes a `[chat] assistant: ...` row to whenever an
 * executor turn completes (see `worker.ts`).
 *
 * Using log_entries instead of the SSE stream sidesteps the race where
 * the runner completes a turn before a `/listen` subscriber attaches, and
 * matches the rest of the test suite's "assert through real wires" rule.
 *
 * Reply-collection contract: each `waitForReply()` waits for an assistant
 * message that arrived *after* the previous one observed. Internally it
 * tracks a high-watermark count of assistant rows; the next call waits
 * for `count + 1`.
 */
import type { AgentCluster } from './cluster'

export interface AssistantReply {
    text: string
    /** ISO timestamp from log_entries. */
    at: string
}

export interface ChatFlowOptions extends RunOptions {
    /** Polling budget for each `waitForReply()`. Default 30s — Haiku is fast but adds up over a turn. */
    waitTimeoutMs?: number
}

export interface AwaitingInputSignal {
    /** The prompt the agent asked for ("What's your name?" etc.). */
    prompt: string | null
    at: string
}

export interface ChatFlow {
    readonly slug: string
    readonly sessionId: Promise<string>
    /** Send a follow-up via `POST /send/:id`. Resolves to the supertest response. */
    send(content: string): Promise<{ status: number }>
    /** Wait for the next assistant message to land in ClickHouse. */
    waitForReply(): Promise<AssistantReply>
    /**
     * Wait for the agent to call ass-server's `ask_for_input` meta tool —
     * the signal that the run has paused for user input. Returns the
     * prompt the agent supplied (if any). Use before `send()` to avoid
     * racing `/send` against an agent that isn't yet listening.
     */
    waitForAwaitingInput(): Promise<AwaitingInputSignal>
    /** Poll until the queue row reaches a terminal state. */
    waitForCompletion(): Promise<void>
}

/**
 * Start a new chat. The first message is sent as the `http_invoke` payload
 * via `POST /run`. Subsequent turns continue with `send()`.
 */
export function chatFlow(
    cluster: AgentCluster,
    slug: string,
    options: ChatFlowOptions & { firstMessage: string }
): ChatFlow {
    const { firstMessage, waitTimeoutMs = 30_000, ...runOpts } = options
    let sessionIdResolver!: (id: string) => void
    const sessionIdPromise = new Promise<string>((resolve) => (sessionIdResolver = resolve))
    let assistantSeen = 0
    let awaitingInputSeen = 0

    const started = (async () => {
        const res = await post(cluster, slug, { ...runOpts, body: { message: firstMessage } })
        if (res.status !== 202) {
            throw new Error(`chatFlow: POST /run returned ${res.status}: ${JSON.stringify(res.body)}`)
        }
        sessionIdResolver(res.body.sessionId as string)
        return res.body.sessionId as string
    })()

    return {
        slug,
        sessionId: sessionIdPromise,
        async send(content: string): Promise<{ status: number }> {
            const sessionId = await started
            const res = await send(cluster, slug, sessionId, content, runOpts)
            return { status: res.status }
        },
        async waitForReply(): Promise<AssistantReply> {
            const sessionId = await started
            const target = assistantSeen + 1
            const start = Date.now()
            while (Date.now() - start < waitTimeoutMs) {
                const rows = await cluster.clickhouse.logsForSession(sessionId)
                const replies = rows
                    .filter((r) => r.message.startsWith('[chat] assistant:'))
                    // CH timestamps come back as 'YYYY-MM-DD HH:MM:SS.ffffff' — lexicographically sortable.
                    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
                if (replies.length >= target) {
                    assistantSeen = target
                    const row = replies[target - 1]
                    return { text: row.message.replace(/^\[chat\] assistant:\s*/, ''), at: row.timestamp }
                }
                await new Promise((res) => setTimeout(res, 250))
            }
            throw new Error(
                `chatFlow.waitForReply timed out after ${waitTimeoutMs}ms (expected reply #${target}; saw ${assistantSeen})`
            )
        },
        async waitForAwaitingInput(): Promise<AwaitingInputSignal> {
            const sessionId = await started
            const target = awaitingInputSeen + 1
            const start = Date.now()
            while (Date.now() - start < waitTimeoutMs) {
                const rows = await cluster.clickhouse.logsForSession(sessionId)
                const events = rows
                    .filter((r) => r.message.startsWith('[meta] awaiting_input'))
                    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
                if (events.length >= target) {
                    awaitingInputSeen = target
                    const row = events[target - 1]
                    // session-logger formats as `[meta] awaiting_input prompt=<oneline>` or just `[meta] awaiting_input`.
                    const match = /^\[meta\] awaiting_input(?: prompt=(.*))?$/.exec(row.message)
                    return { prompt: match?.[1] ?? null, at: row.timestamp }
                }
                await new Promise((res) => setTimeout(res, 250))
            }
            throw new Error(
                `chatFlow.waitForAwaitingInput timed out after ${waitTimeoutMs}ms (expected event #${target}; saw ${awaitingInputSeen})`
            )
        },
        async waitForCompletion(): Promise<void> {
            const sessionId = await started
            const start = Date.now()
            while (Date.now() - start < waitTimeoutMs) {
                const { rows } = await cluster.queue.query<{ status: string }>(
                    `SELECT status FROM agent_sessions WHERE id = $1`,
                    [sessionId]
                )
                const status = rows[0]?.status
                if (status === 'completed' || status === 'failed' || status === 'canceled') {
                    return
                }
                await new Promise((res) => setTimeout(res, 100))
            }
            throw new Error(`chatFlow.waitForCompletion timed out after ${waitTimeoutMs}ms`)
        },
    }
}
