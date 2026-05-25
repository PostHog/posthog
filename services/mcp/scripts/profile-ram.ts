/**
 * RAM profiler for the MCP Cloudflare Worker (entry + Durable Object).
 *
 * Spawns `wrangler dev` with the V8 inspector enabled, drives traffic against
 * the worker, and takes before/after heap snapshots of every inspector target
 * so you can see what's growing per request — the question that matters when
 * a warm DO drifts toward the per-isolate memory ceiling.
 *
 * Run from services/mcp:
 *
 *   pnpm tsx scripts/profile-ram.ts
 *     [--port 8787]
 *     [--inspector-port 9229]
 *     [--requests 25]           # request-loop size between snapshots
 *     [--hit /,/health,/mcp]    # unauth endpoints to warm caches
 *     [--keep-wrangler]         # leave wrangler dev running after run
 *
 * Env:
 *   MCP_BEARER_TOKEN  if set, the request loop hits /mcp with this bearer
 *                     (the only way to instantiate the DO and measure
 *                     per-request growth on it — unauth /mcp 401s before
 *                     reaching the DO).
 *
 * Outputs:
 *   .heapsnapshots/<target>.before.heapsnapshot
 *   .heapsnapshots/<target>.after.heapsnapshot
 *   stdout: per-target diff with top growers by self_size and the
 *           per-request growth rate.
 */
import { spawn, type ChildProcess } from 'child_process'
import { mkdirSync, writeFileSync } from 'fs'
import { createRequire } from 'module'
import { resolve } from 'path'

// workerd's V8 inspector requires an `Origin` header on the WebSocket upgrade;
// Node's built-in `WebSocket` doesn't expose any way to set it, so we fall
// back to the `ws` package via wrangler's dep tree (wrangler → miniflare → ws)
// to avoid adding it as a direct dep. We don't want to add `@types/ws` either
// since this is a one-off profiling script; declare the minimal surface inline.
interface WSInstance {
    on(event: 'message', listener: (data: Buffer) => void): void
    once(event: 'open', listener: () => void): void
    once(event: 'error', listener: (err: Error) => void): void
    once(event: 'close', listener: (code: number, reason: Buffer) => void): void
    send(data: string): void
    close(): void
}
interface WSConstructor {
    new (url: string, opts: { origin: string; maxPayload: number }): WSInstance
}
const requireFromWrangler = createRequire(resolve(process.cwd(), 'node_modules/wrangler/package.json'))
const WSClient: WSConstructor = requireFromWrangler('ws') as WSConstructor

interface InspectorTarget {
    id: string
    title: string
    type?: string
    webSocketDebuggerUrl: string
}

interface CdpMessage {
    id?: number
    method?: string
    params?: Record<string, unknown>
    result?: Record<string, unknown>
    error?: { code: number; message: string }
}

const args = process.argv.slice(2)
const getFlag = (name: string, def: string): string => {
    const i = args.indexOf(name)
    const v = i >= 0 ? args[i + 1] : undefined
    return v ?? def
}
const hasFlag = (name: string): boolean => args.includes(name)

const WORKER_PORT = Number(getFlag('--port', '8787'))
const INSPECTOR_PORT = Number(getFlag('--inspector-port', '9229'))
const REQUEST_LOOP_SIZE = Number(getFlag('--requests', '25'))
// `init` measures per-`initialize` retention only (handshake cost — fresh DO per iteration).
// `tools` extends each iteration with `notifications/initialized` + `tools/list`
// so the diff captures the full session-lifecycle cost — what production
// traffic actually pays per active MCP session (fresh DO per iteration).
// `intra-session` initializes ONCE and then loops N `tools/list` against the
// same `mcp-session-id`, so every request hits the same DO. This is what you
// want when chasing leaks *inside* a long-lived DO (the 256 MiB per-DO ceiling),
// rather than the per-DO startup cost.
// `tool-calls` initializes ONCE, sends `tools/list` to warm the catalog, then
// drives N real `tools/call` requests against the same DO so we measure what
// in-DO tool execution actually retains. The baseline snapshot is taken AFTER
// init+tools/list, so the diff isolates the per-tool-call cost.
const LOOP_MODE_FLAG = getFlag('--mode', 'tools')
const LOOP_MODE: LoopMode =
    LOOP_MODE_FLAG === 'init'
        ? 'initialize-only'
        : LOOP_MODE_FLAG === 'intra-session'
          ? 'intra-session-tools-list'
          : LOOP_MODE_FLAG === 'tool-calls'
            ? 'intra-session-tool-calls'
            : 'init-then-tools-list'
const TOOL_NAME = getFlag('--tool', 'debug-mcp-ui-apps')
const HIT_PATHS = getFlag('--hit', '/,/health,/.well-known/oauth-protected-resource/mcp,/mcp')
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean)
const KEEP_WRANGLER = hasFlag('--keep-wrangler')
const BEARER_TOKEN = process.env.MCP_BEARER_TOKEN
const SNAPSHOT_DIR = resolve(process.cwd(), '.heapsnapshots')
const READY_TIMEOUT_MS = 90_000

mkdirSync(SNAPSHOT_DIR, { recursive: true })

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

async function waitForWorker(): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS
    while (Date.now() < deadline) {
        try {
            const r = await fetch(`http://127.0.0.1:${WORKER_PORT}/`, { signal: AbortSignal.timeout(2000) })
            if (r.status < 600) {
                return
            }
        } catch {
            // not up yet
        }
        await sleep(500)
    }
    throw new Error(`worker did not respond on :${WORKER_PORT} within ${READY_TIMEOUT_MS}ms`)
}

async function discoverTargets(opts: { minCount?: number; timeoutMs?: number } = {}): Promise<InspectorTarget[]> {
    const { minCount = 1, timeoutMs = 15_000 } = opts
    const deadline = Date.now() + timeoutMs
    let last: InspectorTarget[] = []
    while (Date.now() < deadline) {
        try {
            const r = await fetch(`http://127.0.0.1:${INSPECTOR_PORT}/json`, { signal: AbortSignal.timeout(2000) })
            if (r.ok) {
                last = (await r.json()) as InspectorTarget[]
                if (Array.isArray(last) && last.length >= minCount) {
                    return last
                }
            }
        } catch {
            // inspector still warming up
        }
        await sleep(500)
    }
    return last
}

async function exerciseWorker(): Promise<void> {
    for (const path of HIT_PATHS) {
        try {
            const r = await fetch(`http://127.0.0.1:${WORKER_PORT}${path}`, { signal: AbortSignal.timeout(5000) })
            console.info(`[profile-ram] warmup hit ${path} → ${r.status}`)
        } catch (err) {
            console.warn(`[profile-ram] warmup hit ${path} failed: ${(err as Error).message}`)
        }
    }
    await sleep(1000)
}

// MCP JSON-RPC payloads. `initialize` opens a session and the server mints
// `Mcp-Session-Id`; subsequent calls echo that header. `notifications/initialized`
// is the client→server "handshake done" notification some servers require
// before they'll answer tools/list. We send it for safety.
function buildJsonRpcBody(id: number, method: string, params: Record<string, unknown> = {}): string {
    return JSON.stringify({ jsonrpc: '2.0', id, method, params })
}
function buildNotificationBody(method: string, params: Record<string, unknown> = {}): string {
    return JSON.stringify({ jsonrpc: '2.0', method, params })
}

const INITIALIZE_PARAMS = {
    protocolVersion: '2025-06-18',
    capabilities: {},
    clientInfo: { name: 'profile-ram', version: '0.0.1' },
}

type LoopMode = 'initialize-only' | 'init-then-tools-list' | 'intra-session-tools-list' | 'intra-session-tool-calls'

interface LoopResult {
    ok: number
    nonOk: number
    mode: string
    initOk: number
    toolsListOk: number
    avgToolsListBytes: number
    toolCallsOk?: number
    avgToolCallBytes?: number
    liveSessionId?: string
}

async function postMcp(
    headers: Record<string, string>,
    body: string,
    sessionId?: string
): Promise<{ status: number; sessionId: string | undefined; bodySize: number }> {
    const h = { ...headers }
    if (sessionId) {
        h['mcp-session-id'] = sessionId
    }
    const r = await fetch(`http://127.0.0.1:${WORKER_PORT}/mcp`, {
        method: 'POST',
        headers: h,
        body,
        signal: AbortSignal.timeout(15_000),
    })
    const newSession = r.headers.get('mcp-session-id') ?? sessionId
    const buf = await r.arrayBuffer()
    return { status: r.status, sessionId: newSession ?? undefined, bodySize: buf.byteLength }
}

function buildAuthHeaders(): Record<string, string> {
    const h: Record<string, string> = {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
    }
    if (BEARER_TOKEN) {
        h.authorization = `Bearer ${BEARER_TOKEN}`
    }
    return h
}

/**
 * For tool-calls mode: initialize + notifications/initialized + warm tools/list,
 * leaving the DO session alive. Returns the session id so the caller can
 * snapshot the DO target while it's still resident before driving tool calls.
 */
async function primeToolCallSession(
    headers: Record<string, string>
): Promise<{ sessionId: string; warmListBytes: number } | null> {
    const init = await postMcp(headers, buildJsonRpcBody(1, 'initialize', INITIALIZE_PARAMS))
    if (!(init.status >= 200 && init.status < 300) || !init.sessionId) {
        console.warn(`[profile-ram] prime init failed: status=${init.status}`)
        return null
    }
    await postMcp(headers, buildNotificationBody('notifications/initialized'), init.sessionId)
    const warmList = await postMcp(headers, buildJsonRpcBody(2, 'tools/list'), init.sessionId)
    if (!(warmList.status >= 200 && warmList.status < 300)) {
        console.warn(`[profile-ram] prime tools/list failed: status=${warmList.status}`)
    }
    return { sessionId: init.sessionId, warmListBytes: warmList.bodySize }
}

async function driveToolCallsAgainstSession(
    headers: Record<string, string>,
    sessionId: string,
    n: number
): Promise<{ ok: number; nonOk: number; bytesTotal: number }> {
    let ok = 0
    let nonOk = 0
    let bytesTotal = 0
    for (let i = 0; i < n; i++) {
        try {
            const call = await postMcp(
                headers,
                buildJsonRpcBody(i + 3, 'tools/call', {
                    name: TOOL_NAME,
                    arguments: { message: `profile-ram iter ${i}` },
                }),
                sessionId
            )
            if (call.status >= 200 && call.status < 300) {
                ok++
                bytesTotal += call.bodySize
            } else {
                nonOk++
                if (i === 0) {
                    console.warn(`[profile-ram] first tools/call status=${call.status}`)
                }
            }
        } catch (err) {
            nonOk++
            if (i === 0) {
                console.warn(`[profile-ram] first tools/call errored: ${(err as Error).message}`)
            }
        }
    }
    return { ok, nonOk, bytesTotal }
}

async function driveRequestLoop(n: number, loopMode: LoopMode): Promise<LoopResult> {
    let ok = 0
    let nonOk = 0
    let initOk = 0
    let toolsListOk = 0
    let toolsListBytesTotal = 0
    const mode = BEARER_TOKEN ? `authenticated/${loopMode}` : `unauthenticated/${loopMode}`
    console.info(`[profile-ram] driving ${n} ${mode} sessions against /mcp...`)
    const headers: Record<string, string> = {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
    }
    if (BEARER_TOKEN) {
        headers.authorization = `Bearer ${BEARER_TOKEN}`
    }
    if (loopMode === 'intra-session-tool-calls') {
        // One initialize → one notifications/initialized → one tools/list to
        // warm the catalog → N tools/call against the same DO. Returns the
        // sessionId so the caller can take per-DO snapshots while alive.
        let toolCallsOk = 0
        let toolCallsBytesTotal = 0
        try {
            const init = await postMcp(headers, buildJsonRpcBody(1, 'initialize', INITIALIZE_PARAMS))
            if (!(init.status >= 200 && init.status < 300) || !init.sessionId) {
                console.warn(`[profile-ram] tool-calls init failed: status=${init.status}`)
                return { ok, nonOk: 1, mode, initOk, toolsListOk, avgToolsListBytes: 0 }
            }
            ok++
            initOk++
            const sessionId = init.sessionId
            await postMcp(headers, buildNotificationBody('notifications/initialized'), sessionId)
            const warmList = await postMcp(headers, buildJsonRpcBody(2, 'tools/list'), sessionId)
            if (warmList.status >= 200 && warmList.status < 300) {
                ok++
                toolsListOk++
                toolsListBytesTotal += warmList.bodySize
            } else {
                nonOk++
            }
            for (let i = 0; i < n; i++) {
                try {
                    const call = await postMcp(
                        headers,
                        buildJsonRpcBody(i + 3, 'tools/call', {
                            name: TOOL_NAME,
                            arguments: { message: `profile-ram iter ${i}` },
                        }),
                        sessionId
                    )
                    if (call.status >= 200 && call.status < 300) {
                        ok++
                        toolCallsOk++
                        toolCallsBytesTotal += call.bodySize
                    } else {
                        nonOk++
                        if (i === 0) {
                            console.warn(`[profile-ram] first tools/call status=${call.status}`)
                        }
                    }
                } catch (err) {
                    nonOk++
                    if (i === 0) {
                        console.warn(`[profile-ram] first tools/call errored: ${(err as Error).message}`)
                    }
                }
            }
            await sleep(2000)
            return {
                ok,
                nonOk,
                mode,
                initOk,
                toolsListOk,
                avgToolsListBytes: toolsListOk > 0 ? toolsListBytesTotal / toolsListOk : 0,
                toolCallsOk,
                avgToolCallBytes: toolCallsOk > 0 ? toolCallsBytesTotal / toolCallsOk : 0,
                liveSessionId: sessionId,
            }
        } catch (err) {
            console.warn(`[profile-ram] tool-calls setup errored: ${(err as Error).message}`)
            return { ok, nonOk: nonOk + 1, mode, initOk, toolsListOk, avgToolsListBytes: 0 }
        }
    }
    if (loopMode === 'intra-session-tools-list') {
        // One initialize → one notifications/initialized → N tools/list against
        // the same DO. Per-iteration delta reflects intra-DO growth, not the
        // per-DO startup cost.
        try {
            const init = await postMcp(headers, buildJsonRpcBody(1, 'initialize', INITIALIZE_PARAMS))
            if (!(init.status >= 200 && init.status < 300) || !init.sessionId) {
                console.warn(`[profile-ram] intra-session init failed: status=${init.status}`)
                return { ok, nonOk: 1, mode, initOk, toolsListOk, avgToolsListBytes: 0 }
            }
            ok++
            initOk++
            const sessionId = init.sessionId
            await postMcp(headers, buildNotificationBody('notifications/initialized'), sessionId)
            for (let i = 0; i < n; i++) {
                try {
                    const list = await postMcp(headers, buildJsonRpcBody(i + 2, 'tools/list'), sessionId)
                    if (list.status >= 200 && list.status < 300) {
                        ok++
                        toolsListOk++
                        toolsListBytesTotal += list.bodySize
                    } else {
                        nonOk++
                    }
                } catch (err) {
                    nonOk++
                    if (i === 0) {
                        console.warn(`[profile-ram] first tools/list errored: ${(err as Error).message}`)
                    }
                }
            }
        } catch (err) {
            console.warn(`[profile-ram] intra-session setup errored: ${(err as Error).message}`)
            nonOk++
        }
        await sleep(2000)
        return {
            ok,
            nonOk,
            mode,
            initOk,
            toolsListOk,
            avgToolsListBytes: toolsListOk > 0 ? toolsListBytesTotal / toolsListOk : 0,
        }
    }
    for (let i = 0; i < n; i++) {
        try {
            const init = await postMcp(headers, buildJsonRpcBody(1, 'initialize', INITIALIZE_PARAMS))
            if (init.status >= 200 && init.status < 300) {
                ok++
                initOk++
            } else {
                nonOk++
                if (loopMode === 'init-then-tools-list') {
                    continue
                }
            }
            if (loopMode === 'init-then-tools-list' && init.sessionId) {
                // Complete the handshake then ask for the tool list. We don't
                // await initialized's response specifically because it's a
                // notification — no body, no id — but still POST it so any
                // server-side state transition runs.
                await postMcp(headers, buildNotificationBody('notifications/initialized'), init.sessionId)
                const list = await postMcp(headers, buildJsonRpcBody(2, 'tools/list'), init.sessionId)
                if (list.status >= 200 && list.status < 300) {
                    ok++
                    toolsListOk++
                    toolsListBytesTotal += list.bodySize
                } else {
                    nonOk++
                }
            }
        } catch (err) {
            nonOk++
            if (i === 0) {
                console.warn(`[profile-ram] first request errored: ${(err as Error).message}`)
            }
        }
    }
    await sleep(2000)
    return {
        ok,
        nonOk,
        mode,
        initOk,
        toolsListOk,
        avgToolsListBytes: toolsListOk > 0 ? toolsListBytesTotal / toolsListOk : 0,
    }
}

// Persistent CDP session — reused across multiple snapshots so we don't lose
// the heap between calls (closing the WS doesn't reset the isolate, but
// reconnecting is wasteful and `getHeapUsage` is a quick way to monitor
// between snapshots).
class CdpSession {
    private ws: WSInstance
    private nextId = 1
    private pending = new Map<number, (msg: CdpMessage) => void>()
    private chunkBuf: string[] | null = null

    private constructor(ws: WSInstance) {
        this.ws = ws
        ws.on('message', (data) => {
            const msg = JSON.parse(data.toString('utf8')) as CdpMessage
            if (msg.method === 'HeapProfiler.addHeapSnapshotChunk' && this.chunkBuf) {
                this.chunkBuf.push((msg.params as { chunk: string }).chunk)
                return
            }
            if (typeof msg.id === 'number') {
                const cb = this.pending.get(msg.id)
                if (cb) {
                    this.pending.delete(msg.id)
                    cb(msg)
                }
            }
        })
    }

    static async connect(url: string): Promise<CdpSession> {
        const ws = new WSClient(url, {
            origin: `http://127.0.0.1:${INSPECTOR_PORT}`,
            maxPayload: 512 * 1024 * 1024,
        })
        await new Promise<void>((res, rej) => {
            ws.once('open', () => res())
            ws.once('error', (err: Error) => rej(new Error(`ws open failed: ${err.message}`)))
            ws.once('close', (code, reason) =>
                rej(new Error(`ws closed before open: code=${code} reason=${reason.toString()}`))
            )
        })
        const session = new CdpSession(ws)
        await session.send('HeapProfiler.enable')
        return session
    }

    send(method: string, params: Record<string, unknown> = {}): Promise<CdpMessage> {
        const id = this.nextId++
        return new Promise((res, rej) => {
            this.pending.set(id, (msg) => {
                if (msg.error) {
                    rej(new Error(`${method}: ${msg.error.message}`))
                } else {
                    res(msg)
                }
            })
            this.ws.send(JSON.stringify({ id, method, params }))
        })
    }

    async takeHeapSnapshot(): Promise<string> {
        this.chunkBuf = []
        // The takeHeapSnapshot response only resolves after every chunk
        // event has been delivered — so collecting chunks into chunkBuf and
        // joining once the call returns is sufficient.
        await this.send('HeapProfiler.takeHeapSnapshot', { reportProgress: false, captureNumericValue: false })
        const json = this.chunkBuf.join('')
        this.chunkBuf = null
        return json
    }

    async getHeapUsage(): Promise<{ usedSize: number; totalSize: number; embedderHeapUsedSize?: number }> {
        const r = await this.send('Runtime.getHeapUsage')
        return r.result as { usedSize: number; totalSize: number; embedderHeapUsedSize?: number }
    }

    close(): void {
        this.ws.close()
    }
}

interface ClassStat {
    count: number
    selfSize: number
}

interface SnapshotAnalysis {
    totalSelf: number
    nodeCount: number
    byClass: Map<string, ClassStat>
}

function analyzeSnapshot(json: string): SnapshotAnalysis {
    const snap = JSON.parse(json) as {
        snapshot: { meta: { node_fields: string[]; node_types: (string[] | string)[] } }
        nodes: number[]
        strings: string[]
    }
    const { node_fields, node_types } = snap.snapshot.meta
    const fieldCount = node_fields.length
    const typeIdx = node_fields.indexOf('type')
    const nameIdx = node_fields.indexOf('name')
    const selfSizeIdx = node_fields.indexOf('self_size')
    const typeNames = node_types[typeIdx] as string[]

    const byClass = new Map<string, ClassStat>()
    let totalSelf = 0
    const nodes = snap.nodes
    const strings = snap.strings
    const nodeCount = nodes.length / fieldCount

    for (let i = 0; i < nodes.length; i += fieldCount) {
        const typeRaw = nodes[i + typeIdx] ?? 0
        const nameRaw = nodes[i + nameIdx] ?? 0
        const selfSize = nodes[i + selfSizeIdx] ?? 0
        const type = typeNames[typeRaw] ?? '<unknown>'
        const name = strings[nameRaw] ?? ''
        totalSelf += selfSize
        const truncated = name.length > 60 ? name.slice(0, 57) + '...' : name
        const key = `${type}:${truncated || '<no-name>'}`
        const cur = byClass.get(key)
        if (cur) {
            cur.count++
            cur.selfSize += selfSize
        } else {
            byClass.set(key, { count: 1, selfSize })
        }
    }
    return { totalSelf, nodeCount, byClass }
}

function fmtBytes(n: number): string {
    const abs = Math.abs(n)
    const sign = n < 0 ? '-' : ''
    if (abs >= 1024 * 1024) {
        return `${sign}${(abs / 1024 / 1024).toFixed(2)} MiB`
    }
    if (abs >= 1024) {
        return `${sign}${(abs / 1024).toFixed(1)} KiB`
    }
    return `${sign}${abs} B`
}

function printDiff(target: InspectorTarget, before: SnapshotAnalysis, after: SnapshotAnalysis, requests: number): void {
    const totalDelta = after.totalSelf - before.totalSelf
    const perReq = requests > 0 ? totalDelta / requests : 0
    const nodeDelta = after.nodeCount - before.nodeCount

    console.info(`\n=== diff: ${target.title} (${target.id}) ===`)
    console.info(`  before self_size: ${fmtBytes(before.totalSelf)}  nodes=${before.nodeCount.toLocaleString()}`)
    console.info(`  after  self_size: ${fmtBytes(after.totalSelf)}  nodes=${after.nodeCount.toLocaleString()}`)
    console.info(`  Δ total:          ${fmtBytes(totalDelta)}  (${fmtBytes(perReq)}/req over ${requests} requests)`)
    console.info(`  Δ nodes:          ${nodeDelta >= 0 ? '+' : ''}${nodeDelta.toLocaleString()}`)

    const allKeys = new Set([...before.byClass.keys(), ...after.byClass.keys()])
    const diffs: { key: string; delta: number; deltaCount: number; afterSelf: number }[] = []
    for (const key of allKeys) {
        const b = before.byClass.get(key) ?? { count: 0, selfSize: 0 }
        const a = after.byClass.get(key) ?? { count: 0, selfSize: 0 }
        const delta = a.selfSize - b.selfSize
        if (delta !== 0) {
            diffs.push({ key, delta, deltaCount: a.count - b.count, afterSelf: a.selfSize })
        }
    }
    const topGrowers = diffs.sort((x, y) => y.delta - x.delta).slice(0, 20)
    const topShrinkers = diffs.sort((x, y) => x.delta - y.delta).slice(0, 5)

    console.info(`\n  top 20 growers (by Δ self_size):`)
    for (const d of topGrowers) {
        const perReqStr = requests > 0 ? `  ${fmtBytes(d.delta / requests)}/req` : ''
        console.info(
            `    ${fmtBytes(d.delta).padStart(12)}  Δcount=${String(d.deltaCount).padStart(6)}  after=${fmtBytes(d.afterSelf).padStart(11)}${perReqStr}  ${d.key}`
        )
    }
    if (topShrinkers.length > 0 && (topShrinkers[0]?.delta ?? 0) < 0) {
        console.info(`\n  top shrinkers (likely GC'd or replaced):`)
        for (const d of topShrinkers) {
            if (d.delta >= 0) {
                break
            }
            console.info(`    ${fmtBytes(d.delta).padStart(12)}  Δcount=${String(d.deltaCount).padStart(6)}  ${d.key}`)
        }
    }
}

interface TargetState {
    target: InspectorTarget
    session: CdpSession
    before: SnapshotAnalysis
    beforePath: string
}

async function snapshotTarget(
    target: InspectorTarget,
    phase: 'before' | 'after'
): Promise<{ analysis: SnapshotAnalysis; path: string; usage: { usedSize: number; totalSize: number } | null }> {
    const session = await CdpSession.connect(target.webSocketDebuggerUrl)
    let usage: { usedSize: number; totalSize: number } | null = null
    try {
        usage = await session.getHeapUsage()
    } catch {
        // older workerd may not implement Runtime.getHeapUsage
    }
    const json = await session.takeHeapSnapshot()
    session.close()
    const safeName = target.title.replace(/[^a-z0-9_-]+/gi, '_') || target.id
    const path = resolve(SNAPSHOT_DIR, `${safeName}.${phase}.heapsnapshot`)
    writeFileSync(path, json)
    return { analysis: analyzeSnapshot(json), path, usage }
}

async function main(): Promise<void> {
    let wrangler: ChildProcess | undefined
    let exitCode = 0
    try {
        console.info(`[profile-ram] launching wrangler dev on :${WORKER_PORT} (inspector :${INSPECTOR_PORT})...`)
        wrangler = spawn(
            resolve(process.cwd(), 'node_modules/.bin/wrangler'),
            [
                'dev',
                '--port',
                String(WORKER_PORT),
                '--inspector-port',
                String(INSPECTOR_PORT),
                '--show-interactive-dev-session=false',
            ],
            { stdio: ['ignore', 'inherit', 'inherit'], env: { ...process.env } }
        )

        await waitForWorker()
        console.info('[profile-ram] worker ready')
        await exerciseWorker()

        // First-pass: discover whatever targets are alive after the warmup hits.
        // The Durable Object isolate only appears once it's been invoked, which
        // requires an authenticated /mcp request. Without a bearer token we'll
        // typically see just the entry Worker target.
        let targets = await discoverTargets({ minCount: 1 })
        if (targets.length === 0) {
            throw new Error(`no inspector targets at :${INSPECTOR_PORT}/json — is workerd's V8 inspector enabled?`)
        }

        if (LOOP_MODE === 'intra-session-tool-calls') {
            if (!BEARER_TOKEN) {
                throw new Error('tool-calls mode requires MCP_BEARER_TOKEN')
            }
            console.info(
                `[profile-ram] tool-calls mode: priming a DO session (init + tools/list), then driving ${REQUEST_LOOP_SIZE} ${TOOL_NAME} calls`
            )
            const headers = buildAuthHeaders()
            const primed = await primeToolCallSession(headers)
            if (!primed) {
                throw new Error('failed to prime tool-call session')
            }
            console.info(
                `  primed sessionId=${primed.sessionId.slice(0, 12)}…  warm tools/list response = ${fmtBytes(primed.warmListBytes)}`
            )

            // Re-discover targets now that the DO is alive and pinned by sessionId.
            const liveTargets = await discoverTargets({ minCount: targets.length + 1, timeoutMs: 5_000 })
            targets = liveTargets.length > 0 ? liveTargets : targets
            const doTargets = targets.filter(
                (t) => t.title.includes(primed.sessionId) || t.title.includes('streamable-http')
            )
            console.info(`[profile-ram] inspector targets (DO targets marked *):`)
            for (const t of targets) {
                const isDo = doTargets.includes(t)
                console.info(`  ${isDo ? '*' : ' '} ${t.id}  "${t.title}"  ${t.webSocketDebuggerUrl}`)
            }

            // Baseline AFTER prime — the diff isolates per-tools/call retention.
            console.info(`\n[profile-ram] taking baseline snapshots (post-prime)...`)
            const targetStates: TargetState[] = []
            for (const target of targets) {
                const { analysis, path, usage } = await snapshotTarget(target, 'before')
                console.info(
                    `  ${target.title}: self_size=${fmtBytes(analysis.totalSelf)} nodes=${analysis.nodeCount.toLocaleString()}${usage ? ` (Runtime.usedSize=${fmtBytes(usage.usedSize)})` : ''} → ${path}`
                )
                targetStates.push({
                    target,
                    session: await CdpSession.connect(target.webSocketDebuggerUrl),
                    before: analysis,
                    beforePath: path,
                })
            }

            const callResult = await driveToolCallsAgainstSession(headers, primed.sessionId, REQUEST_LOOP_SIZE)
            console.info(
                `[profile-ram] tool-calls done: ok=${callResult.ok} non-ok=${callResult.nonOk}  avg ${TOOL_NAME} response = ${fmtBytes(callResult.ok > 0 ? callResult.bytesTotal / callResult.ok : 0)}`
            )

            await sleep(2000)
            console.info(`\n[profile-ram] taking post-load snapshots...`)
            for (const state of targetStates) {
                state.session.close()
                const { analysis, path, usage } = await snapshotTarget(state.target, 'after')
                console.info(
                    `  ${state.target.title}: self_size=${fmtBytes(analysis.totalSelf)} nodes=${analysis.nodeCount.toLocaleString()}${usage ? ` (Runtime.usedSize=${fmtBytes(usage.usedSize)})` : ''} → ${path}`
                )
                printDiff(state.target, state.before, analysis, REQUEST_LOOP_SIZE)
            }
        } else {
            // If we have a bearer, do one auth'd request first so the DO isolate
            // materializes before we take baselines.
            if (BEARER_TOKEN) {
                console.info('[profile-ram] MCP_BEARER_TOKEN set — sending one authenticated /mcp to spawn the DO...')
                await driveRequestLoop(1, 'initialize-only')
                const next = await discoverTargets({ minCount: targets.length + 1, timeoutMs: 5_000 })
                if (next.length > targets.length) {
                    targets = next
                } else {
                    targets = next.length > 0 ? next : targets
                }
            } else {
                console.info(
                    '[profile-ram] no MCP_BEARER_TOKEN — unauth /mcp will 401 before DO instantiates; measuring entry isolate only.'
                )
            }

            console.info(`[profile-ram] inspector targets:`)
            for (const t of targets) {
                console.info(`  - ${t.id}  "${t.title}"  ${t.webSocketDebuggerUrl}`)
            }

            // Baseline snapshots — one per target. Done before the load loop so
            // the diff reflects what the loop allocated/retained.
            console.info(`\n[profile-ram] taking baseline snapshots...`)
            const targetStates: TargetState[] = []
            for (const target of targets) {
                const { analysis, path, usage } = await snapshotTarget(target, 'before')
                console.info(
                    `  ${target.title}: self_size=${fmtBytes(analysis.totalSelf)} nodes=${analysis.nodeCount.toLocaleString()}${usage ? ` (Runtime.usedSize=${fmtBytes(usage.usedSize)})` : ''} → ${path}`
                )
                const session = await CdpSession.connect(target.webSocketDebuggerUrl)
                targetStates.push({ target, session, before: analysis, beforePath: path })
            }

            // Load loop.
            const loopResult = await driveRequestLoop(REQUEST_LOOP_SIZE, LOOP_MODE)
            console.info(
                `[profile-ram] loop done: ${loopResult.ok} ok / ${loopResult.nonOk} non-ok (${loopResult.mode})`
            )
            console.info(
                `  initialize ok=${loopResult.initOk}  tools/list ok=${loopResult.toolsListOk}` +
                    (loopResult.toolsListOk > 0
                        ? `  avg tools/list response = ${fmtBytes(loopResult.avgToolsListBytes)}`
                        : '')
            )

            // After snapshots + diff.
            console.info(`\n[profile-ram] taking post-load snapshots...`)
            for (const state of targetStates) {
                state.session.close()
                const { analysis, path, usage } = await snapshotTarget(state.target, 'after')
                console.info(
                    `  ${state.target.title}: self_size=${fmtBytes(analysis.totalSelf)} nodes=${analysis.nodeCount.toLocaleString()}${usage ? ` (Runtime.usedSize=${fmtBytes(usage.usedSize)})` : ''} → ${path}`
                )
                printDiff(state.target, state.before, analysis, REQUEST_LOOP_SIZE)
            }
        }

        console.info(`\n[profile-ram] open snapshots in Chrome DevTools → Memory → Load to drill down.`)
        if (!BEARER_TOKEN) {
            console.info(
                `[profile-ram] note: ran without MCP_BEARER_TOKEN. The diff is for the entry isolate only — the DO never instantiated. Set MCP_BEARER_TOKEN to measure per-request growth on the warm DO (the actual 200 MiB ceiling target).`
            )
        }
    } catch (err) {
        console.error(`[profile-ram] ${(err as Error).message}`)
        exitCode = 1
    } finally {
        if (wrangler && !KEEP_WRANGLER) {
            wrangler.kill('SIGTERM')
            await new Promise<void>((res) => {
                wrangler!.on('exit', () => res())
                setTimeout(() => res(), 3000)
            })
        } else if (KEEP_WRANGLER && wrangler) {
            console.info(`[profile-ram] --keep-wrangler set; leaving wrangler dev running (pid=${wrangler.pid})`)
        }
        process.exit(exitCode)
    }
}

void main()
