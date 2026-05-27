import type { Principal } from '@repo/ass-server/types'
/**
 * Thin client helpers bound to a running `AgentCluster` — supertest for HTTP,
 * a SSE collector for `/listen`, Slack signature helper, plus a couple of
 * queue / DB read helpers.
 *
 * All keep the cluster as their single source of truth so tests don't repeat
 * the `Host`-header / URL ceremony.
 */
import { createHmac } from 'node:crypto'
import supertest from 'supertest'

import type { AgentCluster } from './cluster'

/** Compose the Host header for an agent's slug — what `RevisionResolver` expects. */
export function hostFor(slug: string): string {
    return `${slug}.e2e.test`
}

export type IngressRequest = supertest.Test

export interface RunOptions {
    /** Bearer token for `auth: pat` agents. */
    pat?: string
    /** Value to send in the configured shared-secret header (defaults to `x-shared-secret`). */
    sharedSecret?: { header?: string; value: string }
    /** When set, presents `x-posthog-internal: <secret>` for `auth: posthog_internal` agents. */
    internalSecret?: string
    /** JSON body — default `{}`. */
    body?: unknown
}

/** Issue `POST /run` against the agent for `slug`, returning the supertest Test for chaining. */
export function post(cluster: AgentCluster, slug: string, opts: RunOptions = {}): IngressRequest {
    let req = supertest(cluster.ingressUrl)
        .post('/run')
        .set('x-original-host', hostFor(slug))
        .set('content-type', 'application/json')
    if (opts.pat) {
        req = req.set('authorization', `Bearer ${opts.pat}`)
    }
    if (opts.sharedSecret) {
        req = req.set(opts.sharedSecret.header ?? 'x-shared-secret', opts.sharedSecret.value)
    }
    if (opts.internalSecret) {
        req = req.set(cluster.internalHeader, opts.internalSecret)
    }
    return req.send(JSON.stringify(opts.body ?? {}))
}

/** Issue `POST /cancel/:id` with the same auth shape as `post()`. */
export function cancel(cluster: AgentCluster, slug: string, sessionId: string, opts: RunOptions = {}): IngressRequest {
    let req = supertest(cluster.ingressUrl)
        .post(`/cancel/${sessionId}`)
        .set('x-original-host', hostFor(slug))
        .set('content-type', 'application/json')
    if (opts.pat) {
        req = req.set('authorization', `Bearer ${opts.pat}`)
    }
    if (opts.sharedSecret) {
        req = req.set(opts.sharedSecret.header ?? 'x-shared-secret', opts.sharedSecret.value)
    }
    if (opts.internalSecret) {
        req = req.set(cluster.internalHeader, opts.internalSecret)
    }
    return req.send({})
}

/** Issue `POST /send/:id` with the same auth shape as `post()`. */
export function send(
    cluster: AgentCluster,
    slug: string,
    sessionId: string,
    content: string,
    opts: RunOptions = {}
): IngressRequest {
    let req = supertest(cluster.ingressUrl)
        .post(`/send/${sessionId}`)
        .set('x-original-host', hostFor(slug))
        .set('content-type', 'application/json')
    if (opts.pat) {
        req = req.set('authorization', `Bearer ${opts.pat}`)
    }
    if (opts.sharedSecret) {
        req = req.set(opts.sharedSecret.header ?? 'x-shared-secret', opts.sharedSecret.value)
    }
    if (opts.internalSecret) {
        req = req.set(cluster.internalHeader, opts.internalSecret)
    }
    return req.send({ content })
}

/* ===== Slack ===== */

export interface PostSlackOptions {
    /** Slack workspace id. */
    teamId: string
    /** Slack user id. */
    userId: string
    /** `event_callback` subtype. Default: `app_mention`. */
    eventType?: string
    /** Slack signing secret — must match what the agent was deployed with. */
    signingSecret: string
    /** Optional extra fields merged into the `event` object. */
    extraEvent?: Record<string, unknown>
}

export function postSlack(cluster: AgentCluster, slug: string, opts: PostSlackOptions): IngressRequest {
    const payload = {
        type: 'event_callback',
        team_id: opts.teamId,
        event: {
            type: opts.eventType ?? 'app_mention',
            channel: 'C_TEST',
            user: opts.userId,
            text: 'e2e',
            ...opts.extraEvent,
        },
    }
    const body = JSON.stringify(payload)
    const ts = String(Math.floor(Date.now() / 1000))
    const signature = 'v0=' + createHmac('sha256', opts.signingSecret).update(`v0:${ts}:${body}`).digest('hex')
    return supertest(cluster.ingressUrl)
        .post('/webhooks/slack')
        .set('x-original-host', hostFor(slug))
        .set('content-type', 'application/json')
        .set('x-slack-signature', signature)
        .set('x-slack-request-timestamp', ts)
        .send(body)
}

/* ===== Queue / DB reads ===== */

/** Read the principal stamped on a session at creation. `null` for public agents; `undefined` for unknown sessions. */
export async function readPrincipal(cluster: AgentCluster, sessionId: string): Promise<Principal | null | undefined> {
    return cluster.queueManager.getPrincipal(sessionId)
}

export interface SessionStateView {
    messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string; at?: string }>
    pendingInputs: Array<{ at: string; content: string }>
    initialInput: Record<string, unknown> | null
    turnCount: number
}

export interface SessionRowView {
    status: string
    state: SessionStateView | null
    pendingInputsColumn: Array<{ at: string; content: string }>
    scheduledAt: string
}

/**
 * Read the queue row's full conversation state: deserialized `state`
 * BYTEA (messages, turnCount, initialInput) PLUS the standalone
 * `pending_inputs` JSONB column. The two surfaces — state and pending
 * inputs — are tracked separately so an `/send` append doesn't race
 * with the worker's state writeback (see migrations/20260527…).
 *
 * Returns `null` when no session row exists.
 */
export async function readSessionRow(cluster: AgentCluster, sessionId: string): Promise<SessionRowView | null> {
    const { rows } = await cluster.queue.query<{
        status: string
        state: Buffer | null
        pending_inputs: Array<{ at: string; content: string }>
        scheduled: string
    }>(`SELECT status, state, pending_inputs, scheduled FROM agent_sessions WHERE id = $1`, [sessionId])
    if (rows.length === 0) {
        return null
    }
    const row = rows[0]
    return {
        status: row.status,
        state: row.state ? (JSON.parse(row.state.toString('utf8')) as SessionStateView) : null,
        pendingInputsColumn: row.pending_inputs ?? [],
        scheduledAt: row.scheduled,
    }
}

/** Read the session row's status from the queue DB. Useful for asserting the runner picked it up. */
export async function readSessionStatus(cluster: AgentCluster, sessionId: string): Promise<string | null> {
    const { rows } = await cluster.queue.query<{ status: string }>(`SELECT status FROM agent_sessions WHERE id = $1`, [
        sessionId,
    ])
    return rows[0]?.status ?? null
}

/**
 * Poll `readSessionStatus` until it lands in one of the expected statuses,
 * or the timeout elapses. Returns the matched status; throws on timeout
 * with the last status seen. Useful for "wait for runner to ack".
 */
export async function waitForStatus(
    cluster: AgentCluster,
    sessionId: string,
    expected: ReadonlyArray<'completed' | 'failed' | 'canceled' | 'running' | 'available'>,
    opts: { timeoutMs?: number; intervalMs?: number } = {}
): Promise<string> {
    const timeout = opts.timeoutMs ?? 5_000
    const interval = opts.intervalMs ?? 50
    const start = Date.now()
    let lastStatus: string | null = null
    while (Date.now() - start < timeout) {
        lastStatus = await readSessionStatus(cluster, sessionId)
        if (lastStatus && expected.includes(lastStatus as (typeof expected)[number])) {
            return lastStatus
        }
        await new Promise((res) => setTimeout(res, interval))
    }
    throw new Error(
        `waitForStatus(${sessionId}) timed out after ${timeout}ms — last status: ${lastStatus ?? '<no row>'}, expected one of [${expected.join(', ')}]`
    )
}

/**
 * Poll the session row until it reaches `state.turnCount >= n` AND
 * the queue status is back to `available` (i.e. parked after
 * `awaiting_input`). Use to synchronise on "the agent has finished
 * turn N and is awaiting the next /send."
 */
export async function waitForAwaitingInput(
    cluster: AgentCluster,
    sessionId: string,
    opts: { afterTurn?: number; timeoutMs?: number; intervalMs?: number } = {}
): Promise<SessionRowView> {
    const target = opts.afterTurn ?? 1
    const timeout = opts.timeoutMs ?? 10_000
    const interval = opts.intervalMs ?? 50
    const start = Date.now()
    let last: SessionRowView | null = null
    while (Date.now() - start < timeout) {
        last = await readSessionRow(cluster, sessionId)
        if (last && last.status === 'available' && (last.state?.turnCount ?? 0) >= target) {
            return last
        }
        await new Promise((res) => setTimeout(res, interval))
    }
    throw new Error(
        `waitForAwaitingInput(${sessionId}) timed out after ${timeout}ms — last: status=${last?.status ?? '<no row>'}, turnCount=${last?.state?.turnCount ?? '?'}, expected turnCount >= ${target} + status=available`
    )
}

/* ===== SSE ===== */

export interface SseEvent {
    event: string
    data: unknown
}

/**
 * Subscribe to `/listen/:id` and collect events until `done` is seen or
 * `timeoutMs` elapses. Returns the events in arrival order (including
 * replay).
 */
export async function collectSse(
    cluster: AgentCluster,
    slug: string,
    sessionId: string,
    opts: { pat?: string; timeoutMs?: number } = {}
): Promise<SseEvent[]> {
    const headers: Record<string, string> = {
        'x-original-host': hostFor(slug),
        accept: 'text/event-stream',
    }
    if (opts.pat) {
        headers.authorization = `Bearer ${opts.pat}`
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 5_000)
    let res: Response
    try {
        res = await fetch(`${cluster.ingressUrl}/listen/${sessionId}`, {
            headers,
            signal: controller.signal,
        })
    } catch (err) {
        clearTimeout(timeout)
        throw err
    }
    if (!res.body) {
        clearTimeout(timeout)
        throw new Error(`collectSse: no body (status ${res.status})`)
    }
    const events: SseEvent[] = []
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
        while (true) {
            const { value, done } = await reader.read()
            if (done) {
                break
            }
            buffer += decoder.decode(value, { stream: true })
            let idx: number
            // SSE frames are separated by a blank line.
            while ((idx = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, idx)
                buffer = buffer.slice(idx + 2)
                const parsed = parseSseFrame(frame)
                if (parsed) {
                    events.push(parsed)
                    if (
                        parsed.event === 'done' ||
                        parsed.event === 'session_completed' ||
                        parsed.event === 'session_failed'
                    ) {
                        clearTimeout(timeout)
                        controller.abort()
                        return events
                    }
                }
            }
        }
    } catch (err) {
        // AbortError is the timeout path — return what we have.
        if ((err as { name?: string }).name !== 'AbortError') {
            throw err
        }
    } finally {
        clearTimeout(timeout)
    }
    return events
}

function parseSseFrame(frame: string): SseEvent | null {
    let event: string | null = null
    const dataLines: string[] = []
    for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) {
            event = line.slice('event:'.length).trim()
        } else if (line.startsWith('data:')) {
            dataLines.push(line.slice('data:'.length).trim())
        }
    }
    if (!event) {
        return null
    }
    const dataText = dataLines.join('\n')
    let data: unknown = dataText
    if (dataText.length > 0) {
        try {
            data = JSON.parse(dataText)
        } catch {
            /* keep as string */
        }
    }
    return { event, data }
}
